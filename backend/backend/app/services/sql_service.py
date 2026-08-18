"""Schema reading and SQL execution services."""
import hashlib
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from loguru import logger

from app.config.settings import settings
from app.database import db
from app.database.system_store import system_store
from app.database.context import DatabaseContext, db_context_manager, compute_db_fingerprint
import json


class SchemaCacheEntry:
    """Represents a cached schema entry with database fingerprint and timestamp."""

    def __init__(
        self,
        schema: dict[str, Any],
        schema_text: str,
        fingerprint: str,
        timestamp: float,
        recommended_questions: list[dict[str, Any]] | None = None,
        explorer_data: dict[str, Any] | None = None,
    ):
        self.schema = schema
        self.schema_text = schema_text
        self.fingerprint = fingerprint
        self.timestamp = timestamp
        self.recommended_questions = recommended_questions or []
        self.explorer_data = explorer_data or {}

    def is_expired(self, ttl: int, current_fingerprint: str) -> bool:
        """Check if the cache entry is expired or fingerprint mismatched."""
        if self.fingerprint != current_fingerprint:
            return True
        if ttl > 0 and (time.time() - self.timestamp) > ttl:
            return True
        return False

    def to_dict(self):
        return {
            "schema": self.schema,
            "schema_text": self.schema_text,
            "fingerprint": self.fingerprint,
            "timestamp": self.timestamp,
            "recommended_questions": self.recommended_questions,
            "explorer_data": self.explorer_data,
        }

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            schema=data.get("schema", {}),
            schema_text=data.get("schema_text", ""),
            fingerprint=data.get("fingerprint", ""),
            timestamp=data.get("timestamp", 0.0),
            recommended_questions=data.get("recommended_questions"),
            explorer_data=data.get("explorer_data"),
        )


def is_safe_semantic_sample_column(col_name: str) -> bool:
    """Checks if a column is safe for value profiling (avoids PII/secrets/free-form text)."""
    name = col_name.lower()
    deny_keywords = (
        "password", "passwd", "pwd", "ssn", "secret", "token", "key",
        "card", "cvv", "auth", "credential", "private", "iban", "swift",
        "email", "phone", "mobile", "address", "street", "zip",
        "note", "comment", "body", "description", "content", "payload",
        "blob", "json", "xml", "html", "hash", "salt", "signature"
    )
    if any(k in name for k in deny_keywords):
        return False
    
    allow_keywords = (
        "status", "type", "kind", "category", "gender", "tier",
        "country", "state", "city", "region", "currency", "code",
        "priority", "segment", "department", "role", "plan", "flag",
        "mode", "source", "medium", "channel", "brand", "level"
    )
    return any(k in name for k in allow_keywords) or len(name) <= 15


class SchemaService:
    """
    Discovers database schema automatically using SQLAlchemy Inspector
    with thread-safe, fingerprint-aware, and TTL-driven caching.
    """

    _lock = threading.RLock()

    def __init__(self, bind_engine=None):
        self._bind_engine = bind_engine
        self.ttl = settings.schema_cache_ttl

    @property
    def engine(self):
        if self._bind_engine is not None:
            return self._bind_engine
        return db.get_engine()

    @property
    def inspector(self):
        return inspect(self.engine)

    def _get_db_fingerprint(self) -> str:
        """Generate a unique fingerprint based on database identity and file state."""
        return compute_db_fingerprint(self.engine)

    def get_data_freshness_token(self) -> str:
        """Return a dynamic data freshness token for mutable dataset caching."""
        try:
            url_str = str(self.engine.url)
            if url_str.startswith("sqlite"):
                db_path = getattr(self.engine.url, "database", None)
                if db_path and os.path.exists(db_path):
                    stat = os.stat(db_path)
                    return f"mt_{stat.st_mtime_ns}_sz_{stat.st_size}"
            elif "postgres" in url_str:
                with self.engine.connect() as conn:
                    try:
                        res = conn.execute(text("SELECT pg_current_wal_lsn()::text")).scalar()
                        if res:
                            return f"wal_{res}"
                    except Exception:
                        pass
        except Exception:
            pass
        return ""

    def _populate_context_from_entry(self, entry: SchemaCacheEntry, fingerprint: str) -> DatabaseContext:
        """Populate or update the in-RAM DatabaseContext from a SchemaCacheEntry."""
        ctx = db_context_manager.get(fingerprint)
        if ctx is None:
            ctx = DatabaseContext(
                fingerprint=fingerprint,
                url=str(self.engine.url),
                dialect=self.get_database_type().lower(),
                database_name=self.get_database_name(),
                engine=self.engine,
                schema=entry.schema,
                schema_text=entry.schema_text,
                explorer_data=entry.explorer_data,
                recommended_questions=entry.recommended_questions,
                table_names_set=set(entry.schema.keys()),
                ttl=self.ttl,
            )
        else:
            ctx.schema = entry.schema
            ctx.schema_text = entry.schema_text
            ctx.explorer_data = entry.explorer_data
            ctx.recommended_questions = entry.recommended_questions
        # Set in RAM db_context_manager BEFORE building downstream indexes,
        # so any nested calls to get_schema / _get_valid_entry immediately hit RAM without recursion.
        db_context_manager.set(fingerprint, ctx)
        ctx.ensure_indexes()
        return ctx

    def get_database_context(self) -> DatabaseContext:
        """Return the DatabaseContext singleton directly from RAM (0ms), or build and cache it."""
        fingerprint = self._get_db_fingerprint()
        ctx = db_context_manager.get(fingerprint)
        if ctx and ctx.schema:
            return ctx

        with self._lock:
            ctx = db_context_manager.get(fingerprint)
            if ctx and ctx.schema:
                return ctx

            entry = self._get_valid_entry()
            if entry and entry.schema:
                return self._populate_context_from_entry(entry, fingerprint)

            self.refresh_cache()
            ctx = db_context_manager.get(fingerprint)
            if ctx and ctx.schema:
                return ctx

            entry = self._get_valid_entry()
            if entry:
                return self._populate_context_from_entry(entry, fingerprint)

            # Minimal fallback context
            fallback_ctx = DatabaseContext(
                fingerprint=fingerprint,
                url=str(self.engine.url),
                dialect=self.get_database_type().lower(),
                database_name=self.get_database_name(),
                engine=self.engine,
                ttl=self.ttl,
            )
            db_context_manager.set(fingerprint, fallback_ctx)
            return fallback_ctx

    def _get_valid_entry(self) -> Optional[SchemaCacheEntry]:
        fingerprint = self._get_db_fingerprint()
        
        # 1. Fast in-memory RAM check (0ms lookup, zero disk I/O, zero JSON deserialization)
        ctx = db_context_manager.get(fingerprint)
        if ctx and ctx.schema:
            return SchemaCacheEntry(
                schema=ctx.schema,
                schema_text=ctx.schema_text,
                fingerprint=fingerprint,
                timestamp=ctx.created_at,
                recommended_questions=ctx.recommended_questions,
                explorer_data=ctx.explorer_data,
            )

        # 2. Fast local SQLite schema cache on cold start / cache miss
        data = system_store.get_schema_cache(fingerprint)
        if data:
            try:
                entry = SchemaCacheEntry.from_dict(data)
                if not entry.is_expired(self.ttl, fingerprint):
                    self._populate_context_from_entry(entry, fingerprint)
                    return entry
            except Exception as e:
                logger.warning(f"Error parsing schema cache from local store: {e}")
                
        return None

    def get_explorer_data(self) -> dict[str, Any]:
        """Return structured tables, views, procedures, collections, hierarchy tree, and summary."""
        entry = self._get_valid_entry()
        if entry and entry.explorer_data:
            return entry.explorer_data

        with self._lock:
            entry = self._get_valid_entry()
            if entry and entry.explorer_data:
                return entry.explorer_data
            self.refresh_cache()
            entry = self._get_valid_entry()
            return entry.explorer_data if entry else {}

    def get_schema(self) -> dict[str, Any]:
        """Return the full discovered schema, using fingerprint-aware TTL caching."""
        schema, _, _, _ = self.get_schema_with_timing()
        return schema

    def get_schema_with_timing(self) -> Tuple[dict[str, Any], bool, float, float]:
        """Return (schema, cache_hit, cache_lookup_ms, discovery_ms)."""
        t0 = time.perf_counter()
        entry = self._get_valid_entry()
        if entry:
            lookup_ms = (time.perf_counter() - t0) * 1000
            return entry.schema, True, lookup_ms, 0.0

        with self._lock:
            t_lock = time.perf_counter()
            entry = self._get_valid_entry()
            if entry:
                lookup_ms = (time.perf_counter() - t0) * 1000
                return entry.schema, True, lookup_ms, 0.0
            schema, _ = self.refresh_cache()
            disc_ms = (time.perf_counter() - t_lock) * 1000
            lookup_ms = (time.perf_counter() - t0) * 1000
            return schema, False, lookup_ms, disc_ms

    def get_schema_text(self) -> str:
        """Return schema formatted as readable text for LLM prompts, using fingerprint-aware TTL caching."""
        entry = self._get_valid_entry()
        if entry:
            return entry.schema_text

        with self._lock:
            # Double-checked locking pattern
            entry = self._get_valid_entry()
            if entry:
                return entry.schema_text
            _, schema_text = self.refresh_cache()
            return schema_text

    def get_database_type(self) -> str:
        """Return the uppercase dialect name (e.g. SQLITE, POSTGRESQL)."""
        try:
            dialect = self.engine.dialect.name
            return dialect.upper() if dialect else "SQL"
        except Exception:
            return "SQL"

    def get_database_name(self) -> str:
        """Extract a readable database name from the connection URL or file name."""
        try:
            url = self.engine.url
            if hasattr(url, "database") and url.database:
                basename = os.path.basename(str(url.database))
                name = os.path.splitext(basename)[0]
                if name:
                    return name.capitalize()
            if hasattr(url, "host") and url.host:
                return f"{url.host}"
            return "Database"
        except Exception:
            return "Database"

    def get_recommended_questions(self) -> list[dict[str, Any]]:
        """Return recommended dynamic questions based on schema."""
        entry = self._get_valid_entry()
        if entry and getattr(entry, "recommended_questions", None):
            return entry.recommended_questions

        schema = self.get_schema()
        questions = self._generate_recommended_questions(schema)

        entry = self._get_valid_entry()
        if entry:
            entry.recommended_questions = questions
            self._save_entry(entry, self._get_db_fingerprint())
        return questions

    def _generate_recommended_questions(self, schema: dict[str, Any]) -> list[dict[str, Any]]:
        """Generate contextual sample prompt cards based on discovered tables and columns."""
        tables = list(schema.keys())
        if not tables:
            return []

        prompts = []
        icons = ["📊", "📈", "🔍", "🏆", "⚡", "📋"]

        # 1. Total records / summary query for top table
        t1 = tables[0]
        prompts.append({
            "icon": icons[0],
            "title": f"Overview of {t1.capitalize()}",
            "desc": f"Show top 10 records from {t1}",
            "query": f"Show me the top 10 records from {t1}"
        })

        # 2. Count query
        if len(tables) > 1:
            t2 = tables[1]
            prompts.append({
                "icon": icons[1],
                "title": f"Total Count of {t2.capitalize()}",
                "desc": f"Calculate the total number of entries in {t2}",
                "query": f"How many total records are in {t2}?"
            })

        # 3. Aggregation query if numeric column found
        for tbl, info in schema.items():
            num_cols = [c["name"] for c in info.get("columns", []) if any(t in c["type"].upper() for t in ("INT", "FLOAT", "NUMERIC", "DECIMAL", "REAL", "DOUBLE")) and not c.get("primary_key")]
            text_cols = [c["name"] for c in info.get("columns", []) if any(t in c["type"].upper() for t in ("CHAR", "TEXT", "VARCHAR", "STRING"))]
            if num_cols and text_cols:
                prompts.append({
                    "icon": icons[2],
                    "title": f"Top {tbl.capitalize()} Analysis",
                    "desc": f"Group by {text_cols[0]} and sum {num_cols[0]}",
                    "query": f"What are the top 5 {text_cols[0]} by total {num_cols[0]} in {tbl}?"
                })
                break

        # 4. Join / Relationship query if foreign keys exist
        for tbl, info in schema.items():
            fks = info.get("foreign_keys", [])
            if fks:
                ref_tbl = fks[0].get("referred_table")
                if ref_tbl:
                    prompts.append({
                        "icon": icons[3],
                        "title": f"{tbl.capitalize()} & {ref_tbl.capitalize()}",
                        "desc": f"Analyze relationship between {tbl} and {ref_tbl}",
                        "query": f"Show the breakdown of {tbl} joined with {ref_tbl}"
                    })
                    break

        # Fill remaining slots up to 4 if needed
        for t in tables:
            if len(prompts) >= 4:
                break
            if not any(p["title"].endswith(t.capitalize()) for p in prompts):
                prompts.append({
                    "icon": icons[len(prompts) % len(icons)],
                    "title": f"Explore {t.capitalize()}",
                    "desc": f"List summary statistics for {t}",
                    "query": f"Summarize data in the {t} table"
                })

        return prompts[:4]


    @classmethod
    def clear_cache(cls, db_url: Optional[str] = None) -> None:
        """
        Explicitly invalidate schema cache.
        If db_url is provided, invalidates entries matching that URL.
        Otherwise, clears all cached schemas.
        """
        from app.schema_grounding.schema_intelligence import SchemaIntelligenceCache
        
        if db_url:
            target_hash = compute_db_fingerprint(db_url)
            target_hash_prefix = target_hash[:16]
            system_store.clear_schema_cache(db_hash_prefix=target_hash_prefix)
            db_context_manager.invalidate(target_hash)
        else:
            system_store.clear_schema_cache()
            db_context_manager.clear()

        with cls._lock:
            if db_url:
                target_hash = compute_db_fingerprint(db_url)
                target_hash_prefix = target_hash[:16]
                SchemaIntelligenceCache.clear(target_hash_prefix)
            else:
                SchemaIntelligenceCache.clear()

    def _save_entry(self, entry: SchemaCacheEntry, fingerprint: str):
        system_store.set_schema_cache(fingerprint, entry.to_dict())
        self._populate_context_from_entry(entry, fingerprint)

    def refresh_cache(self) -> Tuple[dict[str, Any], str]:
        """Force re-introspection of the database schema and update the cache."""
        fingerprint = self._get_db_fingerprint()

        # Check if persistent CatalogBuilder disk profile exists for instant warm start
        try:
            from app.schema_catalog.catalog_builder import CatalogBuilder
            catalog_builder = CatalogBuilder(schema_service=self)
            cached_catalog = catalog_builder._load_from_store(fingerprint)
            if cached_catalog is not None and cached_catalog.tables:
                schema, schema_text, explorer_data = self._rehydrate_from_catalog(cached_catalog)
                entry = SchemaCacheEntry(
                    schema=schema,
                    schema_text=schema_text,
                    fingerprint=fingerprint,
                    timestamp=time.time(),
                    explorer_data=explorer_data,
                )
                self._save_entry(entry, fingerprint)
                return schema, schema_text
        except Exception:
            pass

        schema, schema_text, explorer_data = self._introspect_schema()
        entry = SchemaCacheEntry(
            schema=schema,
            schema_text=schema_text,
            fingerprint=fingerprint,
            timestamp=time.time(),
            explorer_data=explorer_data,
        )
        self._save_entry(entry, fingerprint)
        return schema, schema_text

    def _rehydrate_from_catalog(self, catalog: Any) -> Tuple[dict[str, Any], str, dict[str, Any]]:
        """Reconstruct (schema, schema_text, explorer_data) instantly from a disk-persisted SchemaCatalog."""
        db_name = getattr(catalog, "database_name", None) or self.get_database_name()
        db_type = getattr(catalog, "dialect", None) or self.get_database_type()

        schema = {}
        tables_list = []
        total_cols = 0
        total_indexes = 0
        total_fks = 0

        lines = ["Database Schema:"]

        for tname, prof in catalog.tables.items():
            cols = []
            for c in prof.columns:
                cols.append({
                    "name": c.name,
                    "type": c.type,
                    "nullable": c.nullable,
                    "default": None,
                    "primary_key": c.primary_key,
                    "samples": c.samples or [],
                    "date_range": c.date_range,
                })

            schema[tname] = {
                "columns": cols,
                "primary_key": prof.primary_key,
                "foreign_keys": prof.foreign_keys,
                "indexes": prof.indexes,
            }

            total_cols += len(cols)
            total_indexes += len(prof.indexes)
            total_fks += len(prof.foreign_keys)

            lines.append(f"\nTable: {tname}")
            for col in cols:
                col_str = f"  - {col['name']} ({col['type']})"
                if not col["nullable"]:
                    col_str += " NOT NULL"
                if col.get("samples"):
                    col_str += f" -- Sample values: {', '.join(repr(s) for s in col['samples'])}"
                if col.get("date_range"):
                    col_str += f" -- Data range: {col['date_range']}"
                lines.append(col_str)
            if prof.primary_key:
                lines.append(f"  PK: {', '.join(prof.primary_key)}")
            for fk in prof.foreign_keys:
                lines.append(
                    f"  FK: {', '.join(fk.get('constrained_columns', []))} -> "
                    f"{fk.get('referred_table')}({', '.join(fk.get('referred_columns', []))})"
                )

            parts = tname.split(".")
            sch_str = parts[0] if len(parts) > 1 else "public"
            table_name = parts[-1]
            tables_list.append({
                "name": table_name,
                "qualified_name": tname,
                "catalog": db_name,
                "schema": sch_str,
                "object_type": "table",
                "columns": cols,
                "primary_key": prof.primary_key,
                "foreign_keys": prof.foreign_keys,
                "indexes": prof.indexes,
                "constraints": [],
                "definition": f"CREATE TABLE {table_name} (\n" + ",\n".join([f"  {c['name']} {c['type']}" for c in cols]) + "\n);",
            })

        schemas_present = set(t.get("schema", "public") for t in tables_list)
        schema_tree_children = []
        for sch in sorted(list(schemas_present)):
            sch_table_children = [
                {
                    "id": f"table-{sch}-{t['name']}",
                    "kind": "table",
                    "name": t["name"],
                    "path": [db_name, sch, "Tables", t["name"]],
                    "meta": {
                        "columns": len(t["columns"]),
                        "indexes": len(t["indexes"]),
                        "foreign_keys": len(t["foreign_keys"]),
                    },
                }
                for t in tables_list if t.get("schema") == sch
            ]
            sch_folders = []
            if sch_table_children:
                sch_folders.append({
                    "id": f"folder-tables-{db_name}-{sch}",
                    "kind": "folder",
                    "name": "Tables",
                    "path": [db_name, sch, "Tables"],
                    "children": sch_table_children,
                })
            schema_tree_children.append({
                "id": f"sch-{sch}-{db_name}",
                "kind": "catalog",
                "name": sch,
                "path": [db_name, sch],
                "children": sch_folders,
            })

        schema_text = "\n".join(lines)
        explorer_data = {
            "tables": tables_list,
            "views": [],
            "procedures": [],
            "collections": [],
            "hierarchy": {"name": db_name, "type": "database", "children": schema_tree_children},
            "schema_tree": schema_tree_children,
            "summary": {
                "database_name": db_name,
                "database_type": db_type,
                "tables": len(catalog.tables),
                "views": 0,
                "procedures": 0,
                "collections": 0,
                "columns": total_cols,
                "indexes": total_indexes,
                "foreign_keys": total_fks,
                "total_tables": len(catalog.tables),
                "total_views": 0,
                "total_columns": total_cols,
                "total_indexes": total_indexes,
                "total_foreign_keys": total_fks,
                "objects": {
                    "tables": len(catalog.tables),
                    "views": 0,
                    "procedures": 0,
                    "collections": 0,
                }
            }
        }
        return schema, schema_text, explorer_data

    _DATE_TYPE_MARKERS = ("DATE", "TIME", "TIMESTAMP")

    def _sample_date_range(self, table_name: str, col_name: str, schema_name: Optional[str] = None) -> Optional[str]:
        """
        Fetch the MIN/MAX of a date/datetime/timestamp column.
        Kept as unbatched fallback for the /refresh/{table_name} API.
        """
        try:
            prep = self.inspector.dialect.identifier_preparer
            quoted_table = prep.quote(table_name)
            if schema_name:
                quoted_table = f"{prep.quote(schema_name)}.{quoted_table}"
            quoted_col = prep.quote(col_name)
            query = (
                f"SELECT MIN({quoted_col}), MAX({quoted_col}) FROM {quoted_table} "
                f"WHERE {quoted_col} IS NOT NULL"
            )
            with self.engine.connect() as conn:
                if self.engine.dialect.name == "postgresql":
                    conn.execute(text(f"SET statement_timeout = {settings.introspection_query_timeout * 1000}"))
                row = conn.execute(text(query)).fetchone()
            if not row or row[0] is None:
                return None
            return f"{row[0]} to {row[1]}"
        except Exception:
            return None

    def _sample_column_values(self, table_name: str, col_name: str, col_type: Any, schema_name: Optional[str] = None) -> list[str]:
        """Fetch up to 3 distinct sample values for a safe semantic text column."""
        if not is_safe_semantic_sample_column(col_name):
            return []
        if not any(t in str(col_type).upper() for t in ("CHAR", "TEXT", "VARCHAR", "STRING")):
            return []
        try:
            prep = self.inspector.dialect.identifier_preparer
            quoted_table = prep.quote(table_name)
            if schema_name:
                quoted_table = f"{prep.quote(schema_name)}.{quoted_table}"
            quoted_col = prep.quote(col_name)
            
            dialect_name = self.engine.dialect.name.lower()
            if dialect_name in ("mssql", "sybase"):
                query = f"SELECT TOP 200 {quoted_col} FROM {quoted_table} WHERE {quoted_col} IS NOT NULL"
            elif dialect_name == "oracle":
                query = f"SELECT {quoted_col} FROM {quoted_table} WHERE {quoted_col} IS NOT NULL FETCH FIRST 200 ROWS ONLY"
            else:
                query = f"SELECT {quoted_col} FROM {quoted_table} WHERE {quoted_col} IS NOT NULL LIMIT 200"

            with self.engine.connect() as conn:
                if dialect_name == "postgresql":
                    conn.execute(text(f"SET statement_timeout = {settings.introspection_query_timeout * 1000}"))
                result = conn.execute(text(query))
                rows = result.fetchall()
            candidates_in_order = [
                str(row[0]).strip() for row in rows
                if row[0] is not None and 0 < len(str(row[0]).strip()) <= 40
            ]
            distinct_vals = list(dict.fromkeys(candidates_in_order))
            return distinct_vals[:3]
        except Exception:
            return []

    def _batch_profile_columns(
        self,
        table_name: str,
        date_cols: list[str],
        text_cols: list[str],
        schema_name: Optional[str] = None,
    ) -> dict[str, dict[str, Any]]:
        """Batched single-query profiling: collect date ranges AND safe text samples in one round-trip."""
        text_cols = [c for c in text_cols if is_safe_semantic_sample_column(c)]
        if not date_cols and not text_cols:
            return {}

        try:
            prep = self.inspector.dialect.identifier_preparer
            quoted_table = prep.quote(table_name)
            if schema_name:
                quoted_table = f"{prep.quote(schema_name)}.{quoted_table}"

            dialect_name = self.engine.dialect.name.lower()

            # Build the SELECT clause:
            # - For each date column: MIN(col), MAX(col)   → 2 result columns
            # - For each text column: col                  → 1 result column
            select_parts: list[str] = []
            col_index_map: dict[str, tuple[str, int, int]] = {}  # col_name → (kind, start_idx, end_idx)
            idx = 0
            for dc in date_cols:
                qc = prep.quote(dc)
                select_parts.append(f"MIN({qc})")
                select_parts.append(f"MAX({qc})")
                col_index_map[dc] = ("date", idx, idx + 1)
                idx += 2

            # Date aggregations + text samples can't be in the same query (GROUP BY conflict).
            # Strategy: issue one aggregation query for dates, one sampling query for text.
            result: dict[str, dict[str, Any]] = {c: {"samples": [], "date_range": None} for c in date_cols + text_cols}

            # --- Date ranges (single aggregation query) ---
            if date_cols and select_parts:
                agg_query = f"SELECT {', '.join(select_parts)} FROM {quoted_table}"
                with self.engine.connect() as conn:
                    if dialect_name == "postgresql":
                        conn.execute(text(f"SET statement_timeout = {settings.introspection_query_timeout * 1000}"))
                    row = conn.execute(text(agg_query)).fetchone()
                if row:
                    for dc in date_cols:
                        _, start_idx, end_idx = col_index_map[dc]
                        min_val, max_val = row[start_idx], row[end_idx]
                        if min_val is not None:
                            result[dc]["date_range"] = f"{min_val} to {max_val}"

            # --- Text samples (single sampling query) ---
            if text_cols:
                quoted_text_cols = [prep.quote(tc) for tc in text_cols]
                select_clause = ", ".join(quoted_text_cols)
                # OR-based WHERE: at least one text column is non-null
                where_parts = [f"{qc} IS NOT NULL" for qc in quoted_text_cols]
                where_clause = " OR ".join(where_parts)

                if dialect_name in ("mssql", "sybase"):
                    sample_query = f"SELECT TOP 200 {select_clause} FROM {quoted_table} WHERE {where_clause}"
                elif dialect_name == "oracle":
                    sample_query = f"SELECT {select_clause} FROM {quoted_table} WHERE {where_clause} FETCH FIRST 200 ROWS ONLY"
                else:
                    sample_query = f"SELECT {select_clause} FROM {quoted_table} WHERE {where_clause} LIMIT 200"

                with self.engine.connect() as conn:
                    if dialect_name == "postgresql":
                        conn.execute(text(f"SET statement_timeout = {settings.introspection_query_timeout * 1000}"))
                    rows = conn.execute(text(sample_query)).fetchall()

                # Extract distinct samples per column from the batched result
                for col_idx, tc in enumerate(text_cols):
                    candidates = [
                        str(row[col_idx]).strip()
                        for row in rows
                        if row[col_idx] is not None and 0 < len(str(row[col_idx]).strip()) <= 40
                    ]
                    distinct_vals = list(dict.fromkeys(candidates))
                    result[tc]["samples"] = distinct_vals[:3]

            return result

        except Exception as e:
            logger.debug("Batched column profiling failed for %s: %s", table_name, e)
            return {c: {"samples": [], "date_range": None} for c in date_cols + text_cols}

    def profile_table_data(self, table_name: str, schema_name: Optional[str] = None, target_columns: Optional[list[dict]] = None, priority_budget: int = 4) -> dict[str, Any]:
        """
        Profile a single table: row count + column samples.

        Uses batched single-query sampling by default (settings.profile_use_batched_sampling).
        Falls back to per-column queries if batching fails or is disabled.

        Args:
            priority_budget: Controls how many text/date columns to sample.
                High-priority tables (FK hubs) get a larger budget.
        """
        from app.schema_catalog.catalog_builder import CatalogBuilder
        
        builder = CatalogBuilder(self)
        fqn = f"{schema_name}.{table_name}" if schema_name and schema_name != "public" else table_name
        
        row_count = builder._safe_row_count(fqn)
        
        col_updates = {}
        
        try:
            if target_columns is not None:
                columns_to_process = target_columns
            else:
                insp_cols = self.inspector.get_columns(table_name, schema=schema_name)
                
                try:
                    pk_info = self.inspector.get_pk_constraint(table_name, schema=schema_name)
                    pk_cols = pk_info.get("constrained_columns", [])
                except Exception:
                    pk_cols = []
                    
                columns_to_process = [
                    {"name": col["name"], "type": str(col["type"]).upper(), "is_pk": col["name"] in pk_cols}
                    for col in insp_cols
                ]

            # Dynamic column budgets based on priority
            max_text_cols = min(settings.profile_max_text_cols_per_table, max(1, priority_budget))
            max_date_cols = min(settings.profile_max_date_cols_per_table, max(1, priority_budget // 2))

            # Classify columns into date and text buckets
            date_col_names: list[str] = []
            text_col_names: list[str] = []
            for col in columns_to_process:
                col_name = col["name"]
                col_type_str = str(col["type"]).upper()
                is_pk = col.get("is_pk", False)

                if any(t in col_type_str for t in self._DATE_TYPE_MARKERS):
                    if len(date_col_names) < max_date_cols:
                        date_col_names.append(col_name)
                elif not is_pk and any(t in col_type_str for t in ("CHAR", "TEXT", "VARCHAR", "STRING")):
                    if len(text_col_names) < max_text_cols:
                        text_col_names.append(col_name)

            # Try batched sampling first (1-2 queries instead of N)
            batched_result = None
            if settings.profile_use_batched_sampling and (date_col_names or text_col_names):
                batched_result = self._batch_profile_columns(
                    table_name, date_col_names, text_col_names, schema_name
                )

            # Build final col_updates — from batched results or fallback to per-column
            for col in columns_to_process:
                col_name = col["name"]
                col_type_str = str(col["type"]).upper()

                samples = []
                date_range = None

                if batched_result and col_name in batched_result:
                    # Use batched results
                    samples = batched_result[col_name].get("samples", [])
                    date_range = batched_result[col_name].get("date_range")
                elif col_name in date_col_names:
                    # Fallback: per-column date range
                    date_range = self._sample_date_range(table_name, col_name, schema_name)
                elif col_name in text_col_names:
                    # Fallback: per-column text sampling
                    samples = self._sample_column_values(table_name, col_name, col_type_str, schema_name)

                col_updates[col_name] = {
                    "samples": samples,
                    "date_range": date_range
                }
        except Exception as e:
            logger.debug(f"Failed to sample data for {table_name}: {e}")
            
        return {
            "row_count": row_count,
            "columns": col_updates
        }

    def _try_bulk_columns(self, insp: Any, schema_name: Optional[str]) -> Optional[dict[str, list[dict]]]:
        """Try calling insp.get_multi_columns(schema=schema_name) and normalize keys to table_name."""
        if not hasattr(insp, "get_multi_columns"):
            return None
        try:
            raw_multi = insp.get_multi_columns(schema=schema_name)
            result = {}
            for k, cols in raw_multi.items():
                tname = k[1] if isinstance(k, tuple) else k
                result[tname] = cols
            return result
        except Exception as e:
            logger.debug("Bulk get_multi_columns failed for schema %s: %s", schema_name, e)
            return None

    def _try_bulk_pk_constraints(self, insp: Any, schema_name: Optional[str]) -> Optional[dict[str, dict]]:
        """Try calling insp.get_multi_pk_constraint(schema=schema_name) and normalize keys to table_name."""
        if not hasattr(insp, "get_multi_pk_constraint"):
            return None
        try:
            raw_multi = insp.get_multi_pk_constraint(schema=schema_name)
            result = {}
            for k, pk in raw_multi.items():
                tname = k[1] if isinstance(k, tuple) else k
                result[tname] = pk
            return result
        except Exception as e:
            logger.debug("Bulk get_multi_pk_constraint failed for schema %s: %s", schema_name, e)
            return None

    def _try_bulk_foreign_keys(self, insp: Any, schema_name: Optional[str]) -> Optional[dict[str, list[dict]]]:
        """Try calling insp.get_multi_foreign_keys(schema=schema_name) and normalize keys to table_name."""
        if not hasattr(insp, "get_multi_foreign_keys"):
            return None
        try:
            raw_multi = insp.get_multi_foreign_keys(schema=schema_name)
            result = {}
            for k, fks in raw_multi.items():
                tname = k[1] if isinstance(k, tuple) else k
                result[tname] = fks
            return result
        except Exception as e:
            logger.debug("Bulk get_multi_foreign_keys failed for schema %s: %s", schema_name, e)
            return None

    def _try_bulk_indexes(self, insp: Any, schema_name: Optional[str]) -> Optional[dict[str, list[dict]]]:
        """Try calling insp.get_multi_indexes(schema=schema_name) and normalize keys to table_name."""
        if not hasattr(insp, "get_multi_indexes"):
            return None
        try:
            raw_multi = insp.get_multi_indexes(schema=schema_name)
            result = {}
            for k, idxs in raw_multi.items():
                tname = k[1] if isinstance(k, tuple) else k
                result[tname] = idxs
            return result
        except Exception as e:
            logger.debug("Bulk get_multi_indexes failed for schema %s: %s", schema_name, e)
            return None

    def _introspect_schema(self) -> Tuple[dict[str, Any], str, dict[str, Any]]:
        """Perform raw database introspection via SQLAlchemy Inspector or MongoDB inspector."""
        url_str = str(self.engine.url)
        db_name = self.get_database_name()
        db_type = self.get_database_type()

        # Handle MongoDB database inspection
        if url_str.startswith("mongodb://") or url_str.startswith("mongodb+srv://"):
            return self._introspect_mongodb(url_str, db_name)

        insp = self.inspector
        schema = {}
        tables_list = []
        views_list = []
        procedures_list = []
        collections_list = []

        total_cols = 0
        total_indexes = 0
        total_fks = 0
        total_constraints = 0

        # Determine schemas to introspect
        target_schemas = [None]
        if db_type == "POSTGRESQL":
            try:
                target_schemas = [s for s in insp.get_schema_names() if s not in ('information_schema', 'pg_catalog', 'pg_toast')]
            except Exception:
                target_schemas = ["public"]



        t_intro_start = time.perf_counter()
        used_bulk_categories = []
        used_legacy_categories = []
        t_bulk_cols_total = 0.0
        t_bulk_pks_total = 0.0
        t_bulk_fks_total = 0.0
        t_bulk_idxs_total = 0.0
        t_tables_disc_total = 0.0

        for schema_name in target_schemas:
            t0 = time.perf_counter()
            # Introspect Tables
            try:
                table_names = insp.get_table_names(schema=schema_name)
            except Exception:
                continue
            t_tables_disc_total += (time.perf_counter() - t0) * 1000

            # Attempt bulk metadata loading per category
            t0 = time.perf_counter()
            bulk_cols_map = self._try_bulk_columns(insp, schema_name)
            t_bulk_cols_total += (time.perf_counter() - t0) * 1000
            if bulk_cols_map is not None:
                if "columns" not in used_bulk_categories:
                    used_bulk_categories.append("columns")
            else:
                if "columns" not in used_legacy_categories:
                    used_legacy_categories.append("columns")

            t0 = time.perf_counter()
            bulk_pks_map = self._try_bulk_pk_constraints(insp, schema_name)
            t_bulk_pks_total += (time.perf_counter() - t0) * 1000
            if bulk_pks_map is not None:
                if "primary_keys" not in used_bulk_categories:
                    used_bulk_categories.append("primary_keys")
            else:
                if "primary_keys" not in used_legacy_categories:
                    used_legacy_categories.append("primary_keys")

            t0 = time.perf_counter()
            bulk_fks_map = self._try_bulk_foreign_keys(insp, schema_name)
            t_bulk_fks_total += (time.perf_counter() - t0) * 1000
            if bulk_fks_map is not None:
                if "foreign_keys" not in used_bulk_categories:
                    used_bulk_categories.append("foreign_keys")
            else:
                if "foreign_keys" not in used_legacy_categories:
                    used_legacy_categories.append("foreign_keys")

            t0 = time.perf_counter()
            bulk_idxs_map = self._try_bulk_indexes(insp, schema_name)
            t_bulk_idxs_total += (time.perf_counter() - t0) * 1000
            if bulk_idxs_map is not None:
                if "indexes" not in used_bulk_categories:
                    used_bulk_categories.append("indexes")
            else:
                if "indexes" not in used_legacy_categories:
                    used_legacy_categories.append("indexes")

            import concurrent.futures

            def process_table(table_name):
                # Primary key discovery
                if bulk_pks_map is not None and table_name in bulk_pks_map:
                    pk = bulk_pks_map[table_name]
                    primary_key_columns = pk.get("constrained_columns", [])
                else:
                    try:
                        pk = insp.get_pk_constraint(table_name, schema=schema_name)
                        primary_key_columns = pk.get("constrained_columns", [])
                    except Exception:
                        primary_key_columns = []

                columns = []
                # Column discovery
                if bulk_cols_map is not None and table_name in bulk_cols_map:
                    insp_cols = bulk_cols_map[table_name]
                else:
                    try:
                        insp_cols = insp.get_columns(table_name, schema=schema_name)
                    except Exception:
                        insp_cols = []

                for col in insp_cols:
                    col_info = {
                        "name": col["name"],
                        "type": str(col["type"]),
                        "nullable": col.get("nullable", True),
                        "default": str(col["default"]) if col.get("default") else None,
                        "primary_key": col["name"] in primary_key_columns,
                        "samples": [],
                        "date_range": None,
                    }
                    columns.append(col_info)

                # Foreign key discovery
                fks = []
                if bulk_fks_map is not None and table_name in bulk_fks_map:
                    raw_fks = bulk_fks_map[table_name]
                else:
                    try:
                        raw_fks = insp.get_foreign_keys(table_name, schema=schema_name)
                    except Exception:
                        raw_fks = []

                for fk in raw_fks:
                    fks.append({
                        "constrained_columns": fk.get("constrained_columns", []),
                        "referred_schema": fk.get("referred_schema"),
                        "referred_table": fk.get("referred_table"),
                        "referred_columns": fk.get("referred_columns", []),
                    })

                # Index discovery
                indexes = []
                if bulk_idxs_map is not None and table_name in bulk_idxs_map:
                    raw_idxs = bulk_idxs_map[table_name]
                else:
                    try:
                        raw_idxs = insp.get_indexes(table_name, schema=schema_name)
                    except Exception:
                        raw_idxs = []

                for idx in raw_idxs:
                    indexes.append({
                        "name": idx["name"],
                        "columns": idx.get("column_names", []),
                        "unique": idx.get("unique", False),
                    })

                qual_name = f"{schema_name}.{table_name}" if schema_name else table_name
                table_schema = {
                    "columns": columns,
                    "primary_key": primary_key_columns,
                    "foreign_keys": fks,
                    "indexes": indexes,
                }

                sch_str = schema_name or "main"
                tbl_obj = {
                    "name": table_name,
                    "qualified_name": f"{db_name}.{sch_str}.{table_name}",
                    "catalog": db_name,
                    "schema": sch_str,
                    "object_type": "table",
                    "columns": columns,
                    "primary_key": primary_key_columns,
                    "foreign_keys": fks,
                    "indexes": indexes,
                    "constraints": [],
                    "definition": f"CREATE TABLE {table_name} (\n" + ",\n".join([f"  {c['name']} {c['type']}" for c in columns]) + "\n);",
                }
                return qual_name, table_schema, tbl_obj

            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                futures = {executor.submit(process_table, tname): tname for tname in table_names}
                for future in concurrent.futures.as_completed(futures):
                    try:
                        qual_name, table_schema, tbl_obj = future.result()
                        schema[qual_name] = table_schema
                        tables_list.append(tbl_obj)
                        
                        total_cols += len(table_schema["columns"])
                        total_indexes += len(table_schema["indexes"])
                        total_fks += len(table_schema["foreign_keys"])
                    except Exception as e:
                        logger.warning(f"Error processing table {futures[future]}: {e}")


            # Introspect Views
            try:
                view_names = insp.get_view_names(schema=schema_name)
                
                def process_view(v_name):
                    try:
                        v_cols = [
                            {
                                "name": c["name"],
                                "type": str(c["type"]),
                                "nullable": c.get("nullable", True),
                                "default": None,
                                "primary_key": False,
                                "samples": [],
                                "date_range": None,
                            }
                            for c in insp.get_columns(v_name, schema=schema_name)
                        ]
                    except Exception:
                        v_cols = []
                    try:
                        v_def = insp.get_view_definition(v_name, schema=schema_name)
                    except Exception:
                        v_def = None

                    sch_str = schema_name or "main"
                    view_obj = {
                        "name": v_name,
                        "qualified_name": f"{db_name}.{sch_str}.{v_name}",
                        "catalog": db_name,
                        "schema": sch_str,
                        "object_type": "view",
                        "columns": v_cols,
                        "primary_key": [],
                        "foreign_keys": [],
                        "indexes": [],
                        "constraints": [],
                        "definition": v_def or f"CREATE VIEW {v_name} AS SELECT * FROM ...;",
                    }
                    return view_obj, v_cols
                
                with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                    view_futures = {executor.submit(process_view, v_name): v_name for v_name in view_names}
                    for future in concurrent.futures.as_completed(view_futures):
                        try:
                            view_obj, v_cols = future.result()
                            views_list.append(view_obj)
                            total_cols += len(v_cols)
                        except Exception as e:
                            logger.warning(f"Error processing view {view_futures[future]}: {e}")
            except Exception:
                pass

        # Build Readable LLM Schema Text
        lines = ["Database Schema:"]
        for table_name, info in schema.items():
            lines.append(f"\nTable: {table_name}")
            for col in info["columns"]:
                col_str = f"  - {col['name']} ({col['type']})"
                if not col["nullable"]:
                    col_str += " NOT NULL"
                if col["default"]:
                    col_str += f" DEFAULT {col['default']}"
                if col.get("samples"):
                    col_str += f" -- Sample values: {', '.join(repr(s) for s in col['samples'])}"
                if col.get("date_range"):
                    col_str += f" -- Data range: {col['date_range']}"
                lines.append(col_str)
            if info["primary_key"]:
                lines.append(f"  PK: {', '.join(info['primary_key'])}")
            for fk in info["foreign_keys"]:
                lines.append(
                    f"  FK: {', '.join(fk['constrained_columns'])} -> "
                    f"{fk['referred_table']}({', '.join(fk['referred_columns'])})"
                )

        schema_text = "\n".join(lines)

        # Build Hierarchical Schema Tree
        schema_folders = []
        
        # Group by schema
        schemas_present = set(t.get("schema", "main") for t in tables_list + views_list)
        schema_tree_children = []
        
        for sch in sorted(list(schemas_present)):
            sch_table_children = [
                {
                    "id": f"table-{sch}-{t['name']}",
                    "kind": "table",
                    "name": t["name"],
                    "path": [db_name, sch, "Tables", t["name"]],
                    "meta": {
                        "columns": len(t["columns"]),
                        "indexes": len(t["indexes"]),
                        "foreign_keys": len(t["foreign_keys"]),
                    },
                }
                for t in tables_list if t.get("schema") == sch
            ]

            sch_view_children = [
                {
                    "id": f"view-{sch}-{v['name']}",
                    "kind": "view",
                    "name": v["name"],
                    "path": [db_name, sch, "Views", v["name"]],
                    "meta": {
                        "columns": len(v["columns"]),
                    },
                }
                for v in views_list if v.get("schema") == sch
            ]
            
            sch_folders = []
            if sch_table_children:
                sch_folders.append({
                    "id": f"folder-tables-{db_name}-{sch}",
                    "kind": "folder",
                    "name": "Tables",
                    "path": [db_name, sch, "Tables"],
                    "children": sch_table_children,
                })
            if sch_view_children:
                sch_folders.append({
                    "id": f"folder-views-{db_name}-{sch}",
                    "kind": "folder",
                    "name": "Views",
                    "path": [db_name, sch, "Views"],
                    "children": sch_view_children,
                })
                
            schema_tree_children.append({
                "id": f"sch-{sch}-{db_name}",
                "kind": "schema",
                "name": sch,
                "path": [db_name, sch],
                "children": sch_folders,
            })

        schema_tree = [
            {
                "id": f"cat-{db_name}",
                "kind": "catalog",
                "name": db_name,
                "path": [db_name],
                "children": schema_tree_children,
            }
        ]

        total_objects = len(tables_list) + len(views_list) + len(procedures_list) + len(collections_list)
        if len(used_bulk_categories) == 4:
            introspection_strategy = "bulk"
        elif len(used_bulk_categories) > 0:
            introspection_strategy = "mixed"
        else:
            introspection_strategy = "legacy"

        t_total_intro_ms = (time.perf_counter() - t_intro_start) * 1000

        summary = {
            "catalogs": 1,
            "schemas": 1,
            "tables": len(tables_list),
            "views": len(views_list),
            "procedures": len(procedures_list),
            "collections": len(collections_list),
            "columns": total_cols,
            "indexes": total_indexes,
            "foreign_keys": total_fks,
            "constraints": total_constraints,
            "objects": total_objects,
            "introspection_strategy": introspection_strategy,
            "introspection_timings": {
                "schema_table_discovery_ms": round(t_tables_disc_total, 2),
                "schema_bulk_columns_ms": round(t_bulk_cols_total, 2),
                "schema_bulk_primary_keys_ms": round(t_bulk_pks_total, 2),
                "schema_bulk_foreign_keys_ms": round(t_bulk_fks_total, 2),
                "schema_bulk_indexes_ms": round(t_bulk_idxs_total, 2),
                "schema_total_introspection_ms": round(t_total_intro_ms, 2),
            }
        }

        explorer_data = {
            "tables": tables_list,
            "views": views_list,
            "procedures": procedures_list,
            "collections": collections_list,
            "schema_tree": schema_tree,
            "summary": summary,
        }

        return schema, schema_text, explorer_data

    def _introspect_mongodb(self, url_str: str, db_name: str) -> Tuple[dict[str, Any], str, dict[str, Any]]:
        """Introspect MongoDB collections and sample field schema."""
        import pymongo
        client = pymongo.MongoClient(url_str, serverSelectionTimeoutMS=5000)
        target_db_name = url_str.rsplit("/", 1)[-1].split("?")[0] or "test"
        db_obj = client[target_db_name]

        schema = {}
        collections_list = []
        total_fields = 0

        col_names = db_obj.list_collection_names()
        for c_name in col_names:
            doc_count = db_obj[c_name].count_documents({})
            sample_docs = list(db_obj[c_name].find().limit(5))

            fields_map = {}
            for doc in sample_docs:
                for k, v in doc.items():
                    if k not in fields_map:
                        fields_map[k] = type(v).__name__

            columns = [
                {
                    "name": k,
                    "type": v,
                    "nullable": True,
                    "default": None,
                    "primary_key": k == "_id",
                    "samples": [],
                    "date_range": None,
                }
                for k, v in fields_map.items()
            ]

            schema[c_name] = {
                "columns": columns,
                "primary_key": ["_id"] if "_id" in fields_map else [],
                "foreign_keys": [],
                "indexes": [],
            }

            col_item = {
                "name": c_name,
                "qualified_name": f"{target_db_name}.{c_name}",
                "catalog": target_db_name.capitalize(),
                "schema": "public",
                "object_type": "collection",
                "columns": columns,
                "primary_key": ["_id"] if "_id" in fields_map else [],
                "foreign_keys": [],
                "indexes": [],
                "constraints": [],
                "document_count": doc_count,
                "definition": f"db.createCollection('{c_name}');",
            }
            collections_list.append(col_item)
            total_fields += len(columns)

        # Build schema text
        lines = ["MongoDB Document Schema:"]
        for c_name, info in schema.items():
            lines.append(f"\nCollection: {c_name}")
            for col in info["columns"]:
                lines.append(f"  - {col['name']} ({col['type']})")

        schema_text = "\n".join(lines)

        col_children = [
            {
                "id": f"col-{c['name']}",
                "kind": "collection",
                "name": c["name"],
                "path": [target_db_name.capitalize(), "public", "Collections", c["name"]],
                "meta": {
                    "document_count": c.get("document_count", 0),
                    "columns": len(c["columns"]),
                },
            }
            for c in collections_list
        ]

        schema_tree = [
            {
                "id": f"cat-{target_db_name}",
                "kind": "catalog",
                "name": target_db_name.capitalize(),
                "path": [target_db_name.capitalize()],
                "children": [
                    {
                        "id": f"sch-{target_db_name}",
                        "kind": "schema",
                        "name": "public",
                        "path": [target_db_name.capitalize(), "public"],
                        "children": [
                            {
                                "id": f"folder-cols-{target_db_name}",
                                "kind": "folder",
                                "name": "Collections",
                                "path": [target_db_name.capitalize(), "public", "Collections"],
                                "children": col_children,
                            }
                        ],
                    }
                ],
            }
        ]

        summary = {
            "catalogs": 1,
            "schemas": 1,
            "tables": 0,
            "views": 0,
            "procedures": 0,
            "collections": len(collections_list),
            "columns": total_fields,
            "indexes": 0,
            "foreign_keys": 0,
            "constraints": 0,
            "objects": len(collections_list),
        }

        explorer_data = {
            "tables": [],
            "views": [],
            "procedures": [],
            "collections": collections_list,
            "schema_tree": schema_tree,
            "summary": summary,
        }

        return schema, schema_text, explorer_data

    # Backward-compatibility property accessors for static _cached_schema and _cached_schema_text
    @property
    def _cached_schema(self) -> Optional[dict[str, Any]]:
        entry = self._get_valid_entry()
        return entry.schema if entry else None

    @property
    def _cached_schema_text(self) -> Optional[str]:
        entry = self._get_valid_entry()
        return entry.schema_text if entry else None


class SQLExecutor:
    """Safely executes validated SQL queries and performs dry-run plan checks."""

    @staticmethod
    def explain(query: str, db: Session) -> Tuple[bool, Optional[str]]:
        """
        Dry-run / plan-check a SQL query using dialect-aware EXPLAIN/PREPARE.
        Validates that tables, columns, and syntax are valid without executing data retrieval.
        """
        import time
        from loguru import logger
        from sqlalchemy import text
        from sqlalchemy.exc import SQLAlchemyError
        from app.utils.validator import get_target_dialect

        clean_query = query.strip().rstrip(";")
        if not clean_query:
            return False, "Empty query"

        dialect_name = "sqlite"
        try:
            if db and db.bind and db.bind.dialect:
                dialect_name = db.bind.dialect.name.lower()
            else:
                dialect_name = get_target_dialect()
        except Exception:
            dialect_name = get_target_dialect()

        if dialect_name == "sqlite":
            explain_sql = f"EXPLAIN QUERY PLAN {clean_query}"
        elif dialect_name in ("postgresql", "postgres", "mysql", "mariadb"):
            explain_sql = f"EXPLAIN {clean_query}"
        elif dialect_name == "oracle":
            explain_sql = f"EXPLAIN PLAN FOR {clean_query}"
        elif dialect_name in ("mssql", "tsql", "sybase"):
            explain_sql = f"SET NOEXEC ON; {clean_query}; SET NOEXEC OFF;"
        else:
            explain_sql = f"EXPLAIN {clean_query}"

        start_time = time.time()
        try:
            db.execute(text(explain_sql))
            duration_ms = (time.time() - start_time) * 1000
            logger.debug("Plan check (EXPLAIN) succeeded in %.2fms for query: %s", duration_ms, clean_query[:100])
            return True, None
        except SQLAlchemyError as e:
            duration_ms = (time.time() - start_time) * 1000
            try:
                db.rollback()
            except Exception:
                pass
            error_msg = str(e)
            logger.debug("Plan check (EXPLAIN) failed in %.2fms: %s", duration_ms, error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = str(e)
            logger.debug("Plan check error: %s", error_msg)
            return False, error_msg

    @staticmethod
    def execute(query: str, db: Session, max_rows: Optional[int] = None) -> list[dict[str, Any]]:
        """Execute a query with scoped read-only controls and bounded results.

        SQLite's ``PRAGMA query_only`` is connection state, not transaction
        state.  It is therefore saved and restored here so a pooled connection
        cannot remain read-only after this execution finishes.
        """
        import sys
        import time
        from loguru import logger
        from app.config.settings import settings

        start_time = time.time()
        timeout_sec = getattr(settings, "cost_guard_timeout_seconds", 15)
        row_limit = max_rows or getattr(settings, "cost_guard_max_returned_rows", 5000)
        byte_limit = getattr(settings, "cost_guard_max_returned_bytes", 10485760)  # 10 MB default
        enforce_read_only = getattr(settings, "enforce_read_only_transactions", True)
        sqlite_query_only_original: Optional[int] = None

        try:
            dialect_name = ""
            if hasattr(db, "dialect") and db.dialect:
                dialect_name = db.dialect.name.lower()
            elif hasattr(db, "bind") and db.bind and db.bind.dialect:
                dialect_name = db.bind.dialect.name.lower()

            # 1. Enforce read-only transaction state & statement timeouts
            if dialect_name in ("postgresql", "postgres"):
                try:
                    if enforce_read_only:
                        db.execute(text("SET TRANSACTION READ ONLY"))
                    db.execute(text(f"SET LOCAL statement_timeout = {int(timeout_sec * 1000)}"))
                except Exception:
                    pass
            elif dialect_name in ("mysql", "mariadb"):
                try:
                    if enforce_read_only:
                        db.execute(text("SET TRANSACTION READ ONLY"))
                    db.execute(text(f"SET SESSION max_execution_time = {int(timeout_sec * 1000)}"))
                except Exception:
                    pass
            elif dialect_name == "sqlite":
                try:
                    if enforce_read_only:
                        # query_only belongs to the underlying connection and can
                        # otherwise leak into the next borrower from the pool.
                        sqlite_query_only_original = int(
                            db.execute(text("PRAGMA query_only")).scalar() or 0
                        )
                        db.execute(text("PRAGMA query_only = ON"))
                except Exception as pragma_err:
                    logger.warning("Unable to enable SQLite query_only for this execution: %s", pragma_err)

            # 2. Execute query
            result = db.execute(text(query))

            # 3. Fetch rows with dual bounds (max rows & max bytes)
            fetched_mappings = result.mappings().fetchmany(row_limit + 1)
            is_row_truncated = len(fetched_mappings) > row_limit
            if is_row_truncated:
                fetched_mappings = fetched_mappings[:row_limit]

            rows: list[dict[str, Any]] = []
            total_bytes = 0
            is_byte_truncated = False

            for mapping in fetched_mappings:
                row_dict = dict(mapping)
                # Approximate byte size of row
                row_bytes = sum(len(str(v).encode("utf-8")) if v is not None else 0 for v in row_dict.values()) + sys.getsizeof(row_dict)
                if total_bytes + row_bytes > byte_limit and rows:
                    is_byte_truncated = True
                    break
                rows.append(row_dict)
                total_bytes += row_bytes

            duration_ms = (time.time() - start_time) * 1000

            if is_row_truncated:
                logger.warning(
                    "Query result truncated to %d rows (exceeded cost_guard_max_returned_rows: %d).",
                    len(rows),
                    row_limit,
                )
            if is_byte_truncated:
                logger.warning(
                    "Query result truncated at %d rows (exceeded cost_guard_max_returned_bytes: %d bytes).",
                    len(rows),
                    byte_limit,
                )

            logger.bind(
                metric="sql_execution",
                duration_ms=duration_ms,
                rows_returned=len(rows),
                bytes_returned=total_bytes,
                truncated=is_row_truncated or is_byte_truncated,
                query=query.strip().replace("\n", " ")[:200]
            ).info(f"Executed SQL query in {duration_ms:.2f}ms, returned {len(rows)} rows ({total_bytes:,} bytes).")

            return rows
        except SQLAlchemyError as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.bind(
                metric="sql_execution",
                duration_ms=duration_ms,
                success=False,
                error=str(e)
            ).error(f"SQL execution failed in {duration_ms:.2f}ms. Error: {e}")
            try:
                db.rollback()
            except Exception:
                pass
            raise RuntimeError(f"SQL execution failed: {e}") from e
        finally:
            if sqlite_query_only_original is not None:
                try:
                    # Restore the precise pre-existing state, rather than always
                    # switching OFF: callers may intentionally own a read-only
                    # connection outside this executor.
                    db.execute(text(f"PRAGMA query_only = {sqlite_query_only_original}"))
                except Exception as restore_err:
                    # This should be loud: a failed restore risks contaminating a
                    # pooled connection's state for a future request.
                    logger.error("Failed to restore SQLite query_only state: %s", restore_err)
