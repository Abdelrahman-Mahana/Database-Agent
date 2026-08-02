"""Schema reading and SQL execution services."""
import hashlib
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import db


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


class SchemaService:
    """
    Discovers database schema automatically using SQLAlchemy Inspector
    with thread-safe, fingerprint-aware, and TTL-driven caching.
    """

    _lock = threading.RLock()
    _cache_store: Dict[str, SchemaCacheEntry] = {}

    def __init__(self, bind_engine=None):
        self._bind_engine = bind_engine
        self.ttl = getattr(settings, "schema_cache_ttl", int(os.getenv("SCHEMA_CACHE_TTL", "3600")))

    @property
    def engine(self):
        if self._bind_engine is not None:
            return self._bind_engine
        return db.engine

    @property
    def inspector(self):
        return inspect(self.engine)

    def _get_db_fingerprint(self) -> str:
        """Generate a unique fingerprint based on database identity and file state."""
        url_str = str(self.engine.url)
        extra = ""
        # If SQLite file database, append file mtime and size to auto-detect schema updates on disk
        if url_str.startswith("sqlite") and self.engine.url.database:
            db_path = self.engine.url.database
            if os.path.exists(db_path):
                stat = os.stat(db_path)
                extra = f":mtime={stat.st_mtime}:size={stat.st_size}"
        raw_key = f"{url_str}{extra}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    def _get_valid_entry(self) -> Optional[SchemaCacheEntry]:
        fingerprint = self._get_db_fingerprint()
        with self._lock:
            entry = self._cache_store.get(fingerprint)
            if entry and not entry.is_expired(self.ttl, fingerprint):
                return entry
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
        entry = self._get_valid_entry()
        if entry:
            return entry.schema

        with self._lock:
            # Double-checked locking pattern
            entry = self._get_valid_entry()
            if entry:
                return entry.schema
            schema, _ = self.refresh_cache()
            return schema

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
        with cls._lock:
            if db_url:
                target_hash_prefix = hashlib.sha256(db_url.encode("utf-8")).hexdigest()[:16]
                keys_to_del = [k for k in cls._cache_store if k.startswith(target_hash_prefix)]
                for k in keys_to_del:
                    del cls._cache_store[k]
            else:
                cls._cache_store.clear()

    def refresh_cache(self) -> Tuple[dict[str, Any], str]:
        """Force re-introspection of the database schema and update the cache."""
        fingerprint = self._get_db_fingerprint()
        schema, schema_text, explorer_data = self._introspect_schema()
        entry = SchemaCacheEntry(
            schema=schema,
            schema_text=schema_text,
            fingerprint=fingerprint,
            timestamp=time.time(),
            explorer_data=explorer_data,
        )
        with self._lock:
            self._cache_store[fingerprint] = entry
        return schema, schema_text

    _DATE_TYPE_MARKERS = ("DATE", "TIME", "TIMESTAMP")

    def _sample_date_range(self, table_name: str, col_name: str) -> Optional[str]:
        """
        Fetch the MIN/MAX of a date/datetime/timestamp column.
        """
        try:
            prep = self.inspector.dialect.identifier_preparer
            quoted_table = prep.quote(table_name)
            quoted_col = prep.quote(col_name)
            query = (
                f"SELECT MIN({quoted_col}), MAX({quoted_col}) FROM {quoted_table} "
                f"WHERE {quoted_col} IS NOT NULL"
            )
            with self.engine.connect() as conn:
                row = conn.execute(text(query)).fetchone()
            if not row or row[0] is None:
                return None
            return f"{row[0]} to {row[1]}"
        except Exception:
            return None

    def _sample_column_values(self, table_name: str, col_name: str, col_type: str) -> list[str]:
        """Fetch up to 3 distinct sample values for a text column."""
        if not any(t in col_type.upper() for t in ("CHAR", "TEXT", "VARCHAR", "STRING")):
            return []
        try:
            prep = self.inspector.dialect.identifier_preparer
            quoted_table = prep.quote(table_name)
            quoted_col = prep.quote(col_name)
            query = (
                f"SELECT {quoted_col} FROM {quoted_table} "
                f"WHERE {quoted_col} IS NOT NULL LIMIT 200"
            )
            with self.engine.connect() as conn:
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

        # Introspect Tables
        table_names = insp.get_table_names()
        for table_name in table_names:
            pk = insp.get_pk_constraint(table_name)
            primary_key_columns = pk.get("constrained_columns", [])
            columns = []
            text_cols_sampled = 0
            for col in insp.get_columns(table_name):
                col_type_str = str(col["type"]).upper()
                col_info = {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                    "default": str(col["default"]) if col.get("default") else None,
                    "primary_key": col["name"] in primary_key_columns,
                    "samples": [],
                    "date_range": None,
                }
                if any(t in col_type_str for t in self._DATE_TYPE_MARKERS):
                    col_info["date_range"] = self._sample_date_range(table_name, col_info["name"])
                elif text_cols_sampled < 8 and not col_info["primary_key"]:
                    samples = self._sample_column_values(table_name, col_info["name"], col_info["type"])
                    if samples:
                        col_info["samples"] = samples
                        text_cols_sampled += 1
                columns.append(col_info)

            fks = []
            for fk in insp.get_foreign_keys(table_name):
                fks.append({
                    "constrained_columns": fk.get("constrained_columns", []),
                    "referred_schema": fk.get("referred_schema"),
                    "referred_table": fk.get("referred_table"),
                    "referred_columns": fk.get("referred_columns", []),
                })

            indexes = []
            for idx in insp.get_indexes(table_name):
                indexes.append({
                    "name": idx["name"],
                    "columns": idx["column_names"],
                    "unique": idx.get("unique", False),
                })

            schema[table_name] = {
                "columns": columns,
                "primary_key": pk.get("constrained_columns", []),
                "foreign_keys": fks,
                "indexes": indexes,
            }

            total_cols += len(columns)
            total_indexes += len(indexes)
            total_fks += len(fks)

            tbl_obj = {
                "name": table_name,
                "qualified_name": f"{db_name}.main.{table_name}",
                "catalog": db_name,
                "schema": "main",
                "object_type": "table",
                "columns": columns,
                "primary_key": pk.get("constrained_columns", []),
                "foreign_keys": fks,
                "indexes": indexes,
                "constraints": [],
                "definition": f"CREATE TABLE {table_name} (\n" + ",\n".join([f"  {c['name']} {c['type']}" for c in columns]) + "\n);",
            }
            tables_list.append(tbl_obj)

        # Introspect Views
        try:
            view_names = insp.get_view_names()
            for v_name in view_names:
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
                        for c in insp.get_columns(v_name)
                    ]
                except Exception:
                    v_cols = []
                try:
                    v_def = insp.get_view_definition(v_name)
                except Exception:
                    v_def = None

                view_obj = {
                    "name": v_name,
                    "qualified_name": f"{db_name}.main.{v_name}",
                    "catalog": db_name,
                    "schema": "main",
                    "object_type": "view",
                    "columns": v_cols,
                    "primary_key": [],
                    "foreign_keys": [],
                    "indexes": [],
                    "constraints": [],
                    "definition": v_def or f"CREATE VIEW {v_name} AS SELECT * FROM ...;",
                }
                views_list.append(view_obj)
                total_cols += len(v_cols)
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
        table_children = [
            {
                "id": f"table-{t['name']}",
                "kind": "table",
                "name": t["name"],
                "path": [db_name, "main", "Tables", t["name"]],
                "meta": {
                    "columns": len(t["columns"]),
                    "indexes": len(t["indexes"]),
                    "foreign_keys": len(t["foreign_keys"]),
                },
            }
            for t in tables_list
        ]

        view_children = [
            {
                "id": f"view-{v['name']}",
                "kind": "view",
                "name": v["name"],
                "path": [db_name, "main", "Views", v["name"]],
                "meta": {
                    "columns": len(v["columns"]),
                },
            }
            for v in views_list
        ]

        schema_folders = []
        if table_children:
            schema_folders.append({
                "id": f"folder-tables-{db_name}",
                "kind": "folder",
                "name": "Tables",
                "path": [db_name, "main", "Tables"],
                "children": table_children,
            })
        if view_children:
            schema_folders.append({
                "id": f"folder-views-{db_name}",
                "kind": "folder",
                "name": "Views",
                "path": [db_name, "main", "Views"],
                "children": view_children,
            })

        schema_tree = [
            {
                "id": f"cat-{db_name}",
                "kind": "catalog",
                "name": db_name,
                "path": [db_name],
                "children": [
                    {
                        "id": f"sch-main-{db_name}",
                        "kind": "schema",
                        "name": "main",
                        "path": [db_name, "main"],
                        "children": schema_folders,
                    }
                ],
            }
        ]

        total_objects = len(tables_list) + len(views_list) + len(procedures_list) + len(collections_list)
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
    """Safely executes validated SQL queries."""

    @staticmethod
    def execute(query: str, db: Session) -> list[dict[str, Any]]:
        """Execute a SQL query, log performance metrics, and return results as a list of dicts."""
        import time
        from loguru import logger

        start_time = time.time()
        try:
            result = db.execute(text(query))
            rows = [dict(row) for row in result.mappings()]
            duration_ms = (time.time() - start_time) * 1000

            logger.bind(
                metric="sql_execution",
                duration_ms=duration_ms,
                rows_returned=len(rows),
                query=query.strip().replace("\n", " ")[:200]
            ).info(f"Executed SQL query in {duration_ms:.2f}ms, returned {len(rows)} rows.")

            return rows
        except SQLAlchemyError as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.bind(
                metric="sql_execution",
                duration_ms=duration_ms,
                success=False,
                error=str(e)
            ).error(f"SQL execution failed in {duration_ms:.2f}ms. Error: {e}")
            raise RuntimeError(f"SQL execution failed: {e}") from e
