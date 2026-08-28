"""Builds and persists the Schema Catalog (Normalized Metadata System of Record).

Supports:
1. Structural schema introspection and statistics calculation.
2. Background statistical profiling and LLM business glossary synthesis.
3. Normalized relational storage on SQLite disk with selective O(K) sub-schema loading.
4. Two-stage hybrid retrieval integration for enterprise databases (10,000+ tables).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from loguru import logger
from sqlalchemy import text

from app.core.config.settings import settings
from app.models.schema_catalog.models import (
    SchemaCatalog,
    TableProfile,
    ColumnProfile,
    DatabaseConnectionRecord,
    SchemaObjectRecord,
    ColumnRecord,
    RelationshipRecord,
    IndexStatsRecord,
    AliasTermRecord,
    CatalogVersionRecord,
)

CATALOG_DIR = Path(settings.schema_catalog_dir)

from app.services.database.system_store import system_store


def set_build_progress(fingerprint: str, progress: dict):
    system_store.set_catalog_progress(fingerprint, progress)


def get_build_progress(fingerprint: str) -> dict:
    return system_store.get_catalog_progress(fingerprint)


class CatalogBuilder:
    """Builds a SchemaCatalog once per DB fingerprint and persists normalized records to disk."""

    def __init__(self, schema_service: Optional[Any] = None):
        if schema_service is None:
            from app.services.sql_service import SchemaService
            schema_service = SchemaService()
        self.schema_service = schema_service
        CATALOG_DIR.mkdir(parents=True, exist_ok=True)

    # -- Public API ---------------------------------------------------

    def get_or_build(self, force_rebuild: bool = False, raw_schema: Optional[dict[str, Any]] = None) -> SchemaCatalog:
        """Return the authoritative catalog for the currently-connected database.

        Checks in-RAM DatabaseContext first (0ms), verifies against authoritative
        persistent storage in SystemStore / SQLite disk, or builds it if missing.
        """
        fingerprint = self.schema_service._get_db_fingerprint()
        from app.services.database.context import db_context_manager
        ctx = db_context_manager.get(fingerprint)

        if not force_rebuild:
            if ctx and ctx.catalog is not None:
                # Verify if persistent store has a newer version
                latest_ver = system_store.get_latest_catalog_version(fingerprint)
                if latest_ver and latest_ver.version > getattr(ctx.catalog, "glossary_version", 0):
                    logger.info(
                        "In-worker DatabaseContext catalog is stale (v%s vs store v%s), rehydrating from store",
                        getattr(ctx.catalog, "glossary_version", 0), latest_ver.version
                    )
                    cached = self._load_from_store(fingerprint)
                    if cached is not None:
                        ctx.catalog = cached
                        ctx.ensure_indexes(force=True)
                        return cached
                return ctx.catalog

            cached = self._load_from_store(fingerprint)
            if cached is not None:
                if ctx is not None:
                    ctx.catalog = cached
                return cached

        if raw_schema is None and ctx is not None and ctx.schema:
            raw_schema = ctx.schema

        catalog = self._build(fingerprint, raw_schema=raw_schema)
        self.save(catalog)
        if ctx is not None:
            ctx.catalog = catalog
        return catalog

    def merge_glossary(self, catalog: SchemaCatalog, glossary: dict) -> SchemaCatalog:
        """Apply a glossary dict (see glossary.py) onto a catalog, bump version, and persist it."""
        for tname, meta in glossary.get("tables", {}).items():
            tprof = catalog.tables.get(tname)
            if not tprof:
                continue
            tprof.description = meta.get("description") or tprof.description
            tprof.synonyms = sorted(set(tprof.synonyms) | set(meta.get("synonyms", [])))

        for key, meta in glossary.get("columns", {}).items():
            if "." not in key:
                continue
            tname, cname = key.split(".", 1)
            tprof = catalog.tables.get(tname)
            if not tprof:
                continue
            for col in tprof.columns:
                if col.name == cname:
                    col.description = meta.get("description") or col.description
                    col.synonyms = sorted(set(col.synonyms) | set(meta.get("synonyms", [])))
                    break

        catalog.glossary_enriched = True
        catalog.bump_version(build_status="completed")
        self.save(catalog)

        # Update in-worker DatabaseContext if active
        from app.services.database.context import db_context_manager
        ctx = db_context_manager.get(catalog.fingerprint)
        if ctx is not None:
            ctx.catalog = catalog
            ctx.ensure_indexes(force=True)

        return catalog

    async def enrich_with_embeddings(self, catalog: SchemaCatalog, force: bool = False) -> SchemaCatalog:
        """Compute + persist table embeddings for semantic retrieval."""
        from app.models.schema_catalog.embedding_retrieval import ensure_table_embeddings
        catalog = await ensure_table_embeddings(catalog, force=force)
        self.save(catalog)

        from app.services.database.context import db_context_manager
        ctx = db_context_manager.get(catalog.fingerprint)
        if ctx is not None:
            ctx.catalog = catalog

        return catalog

    async def build_async(self, fingerprint: str) -> None:
        """Background worker method to asynchronously profile rows and sample values for all tables."""
        import asyncio
        catalog = self._load_from_store(fingerprint)
        if not catalog:
            logger.warning(f"Background build started but no structural catalog found for {fingerprint}")
            return
            
        tables = list(catalog.tables.keys())
        total_tables = len(tables)
        
        progress_state = {
            "status": "profiling",
            "progress_percent": 0.0,
            "tables_processed": 0,
            "total_tables": total_tables
        }
        set_build_progress(fingerprint, progress_state)
        
        logger.info(f"Starting background data profile for {total_tables} tables in {catalog.database_name}")
        
        save_batch_size = max(10, total_tables // 20)
        semaphore = asyncio.Semaphore(15)
        tables_processed = 0
        
        async def profile_single_table(tname):
            nonlocal tables_processed
            try:
                parts = tname.split(".")
                schema_name = parts[0] if len(parts) > 1 else None
                base_table = parts[-1]
                
                tprof = catalog.tables[tname]
                target_columns = [
                    {"name": col.name, "type": col.type, "is_pk": col.primary_key}
                    for col in tprof.columns
                ]
                
                async with semaphore:
                    profile_data = await asyncio.to_thread(
                        self.schema_service.profile_table_data,
                        base_table,
                        schema_name,
                        target_columns
                    )
                
                tprof.row_count = profile_data.get("row_count")
                tprof.profiled = True
                tprof.profile_status = "profiled"
                tprof.last_profiled_at = time.time()

                col_updates = profile_data.get("columns", {})
                for col in tprof.columns:
                    if col.name in col_updates:
                        col.samples = col_updates[col.name].get("samples", [])
                        col.date_range = col_updates[col.name].get("date_range")

                # Persist single-table profiling stats independently into authoritative store
                system_store.update_table_profile_stats(
                    fingerprint=fingerprint,
                    table_name=tname,
                    row_count=tprof.row_count,
                    column_stats=col_updates,
                    profiled_at=tprof.last_profiled_at,
                )
                        
            except Exception as e:
                logger.warning(f"Error profiling table {tname}: {e}")
                
            tables_processed += 1
            progress_percent = round((tables_processed / total_tables) * 100, 1)
            
            progress_state.update({
                "progress_percent": progress_percent,
                "tables_processed": tables_processed
            })
            set_build_progress(fingerprint, progress_state)

        for chunk_idx in range(0, total_tables, save_batch_size):
            chunk = tables[chunk_idx:chunk_idx + save_batch_size]
            tasks = [profile_single_table(tname) for tname in chunk]
            await asyncio.gather(*tasks)
            await asyncio.to_thread(self._save_to_disk, catalog)
                
        catalog.bump_version(build_status="completed")
        self.save(catalog)

        # Update in-worker DatabaseContext cache if active
        from app.services.database.context import db_context_manager
        ctx = db_context_manager.get(fingerprint)
        if ctx is not None:
            ctx.catalog = catalog

        progress_state["status"] = "complete"
        set_build_progress(fingerprint, progress_state)
        logger.info(f"Finished background data profile for {catalog.database_name}")

    # -- Building -------------------------------------------------------

    def _build(self, fingerprint: str, raw_schema: Optional[dict[str, Any]] = None) -> SchemaCatalog:
        t0 = time.time()
        if raw_schema is None:
            from app.services.database.context import db_context_manager
            ctx = db_context_manager.get(fingerprint)
            if ctx and ctx.schema:
                raw_schema = ctx.schema
            else:
                raw_schema = self.schema_service.get_schema()
        dialect = self.schema_service.get_database_type()
        db_name = self.schema_service.get_database_name()

        catalog = SchemaCatalog(fingerprint=fingerprint, dialect=dialect, database_name=db_name)

        fk_degree: dict[str, int] = {t: 0 for t in raw_schema}
        for tname, info in raw_schema.items():
            for fk in info.get("foreign_keys", []):
                ref = fk.get("referred_table")
                fk_degree[tname] = fk_degree.get(tname, 0) + 1
                if ref in fk_degree:
                    fk_degree[ref] = fk_degree.get(ref, 0) + 1

        for tname, info in raw_schema.items():
            fk_cols = {c for fk in info.get("foreign_keys", []) for c in fk.get("constrained_columns", [])}
            columns = [
                ColumnProfile(
                    name=c["name"],
                    type=c["type"],
                    nullable=c.get("nullable", True),
                    primary_key=c.get("primary_key", False),
                    is_foreign_key=c["name"] in fk_cols,
                    samples=[],
                    date_range=None,
                )
                for c in info.get("columns", [])
            ]
            catalog.tables[tname] = TableProfile(
                name=tname,
                columns=columns,
                primary_key=info.get("primary_key", []),
                foreign_keys=info.get("foreign_keys", []),
                indexes=info.get("indexes", []),
                row_count=None,
                fk_degree=fk_degree.get(tname, 0),
            )

        catalog.built_at = time.time()
        logger.info(
            "SchemaCatalog built for %s (%d tables) in %.1fms",
            db_name, len(catalog.tables), (time.time() - t0) * 1000,
        )
        return catalog

    def _safe_row_count(self, table_name: str) -> Optional[int]:
        try:
            dialect = self.schema_service.engine.dialect.name
            parts = table_name.split(".")
            base_table = parts[-1]
            
            if dialect == "postgresql":
                query = text("SELECT reltuples::bigint AS estimate FROM pg_class WHERE relname = :table")
                with self.schema_service.engine.connect() as conn:
                    result = conn.execute(query, {"table": base_table})
                    row = result.fetchone()
                    if row and row[0] is not None and row[0] >= 0:
                        return int(row[0])

            prep = self.schema_service.inspector.dialect.identifier_preparer
            if len(parts) == 2:
                quoted = f"{prep.quote(parts[0])}.{prep.quote(parts[1])}"
            else:
                quoted = prep.quote(table_name)

            with self.schema_service.engine.connect() as conn:
                if dialect == "postgresql":
                    conn.execute(text("SET statement_timeout = 2000"))
                result = conn.execute(text(f"SELECT COUNT(*) FROM {quoted}"))
                row = result.fetchone()
            return int(row[0]) if row else None
        except Exception:
            return None

    # -- Persistence (Normalized Entity Relational System) ----------------

    def _path_for(self, fingerprint: str) -> Path:
        return CATALOG_DIR / f"{fingerprint}.db"

    def _init_db(self, path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS tables (name TEXT PRIMARY KEY, profile_json TEXT)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS catalog_database_connection (
                connection_id TEXT PRIMARY KEY,
                database_name TEXT,
                tenant_id TEXT,
                dialect TEXT,
                fingerprint TEXT,
                version TEXT,
                last_introspected_at REAL,
                last_profiled_at REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS catalog_schema_object (
                object_id TEXT PRIMARY KEY,
                fingerprint TEXT,
                schema_name TEXT,
                object_name TEXT,
                object_type TEXT,
                row_count_estimate INTEGER,
                description TEXT,
                status TEXT,
                fk_degree INTEGER
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_obj_fp_name ON catalog_schema_object (fingerprint, object_name)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS catalog_column (
                column_id TEXT PRIMARY KEY,
                object_id TEXT,
                fingerprint TEXT,
                name TEXT,
                normalized_name TEXT,
                data_type TEXT,
                nullable INTEGER,
                primary_key INTEGER,
                is_foreign_key INTEGER,
                semantic_type TEXT,
                description TEXT,
                synonyms_json TEXT,
                null_fraction REAL,
                distinct_estimate INTEGER,
                samples_json TEXT,
                date_range TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_col_obj_fp ON catalog_column (object_id, fingerprint)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS catalog_relationship (
                relationship_id TEXT PRIMARY KEY,
                fingerprint TEXT,
                source_object TEXT,
                source_column TEXT,
                target_object TEXT,
                target_column TEXT,
                relationship_type TEXT,
                confidence REAL,
                source TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rel_fp_objs ON catalog_relationship (fingerprint, source_object, target_object)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS catalog_index_stats (
                index_id TEXT PRIMARY KEY,
                object_id TEXT,
                fingerprint TEXT,
                index_name TEXT,
                columns_json TEXT,
                uniqueness INTEGER,
                selectivity_hints TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS catalog_alias_term (
                alias_id TEXT PRIMARY KEY,
                fingerprint TEXT,
                canonical_id TEXT,
                entity_type TEXT,
                term TEXT,
                language TEXT,
                source TEXT,
                confidence REAL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alias_fp_term ON catalog_alias_term (fingerprint, term)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS catalog_version (
                version_id TEXT PRIMARY KEY,
                fingerprint TEXT,
                version INTEGER,
                change_timestamp REAL,
                build_status TEXT,
                job_id TEXT
            )
        """)
        return conn

    def load_table_subset(self, fingerprint: str, table_names: list[str]) -> dict[str, TableProfile]:
        """Selectively loads only specified candidate tables and their columns in O(K) time."""
        # 1. Try authoritative SystemStore first
        store_res = system_store.load_table_subset(fingerprint, table_names)
        if store_res:
            return store_res

        # 2. Fallback to SQLite disk file
        path = self._path_for(fingerprint)
        if not path.exists() or not table_names:
            return {}

        results: dict[str, TableProfile] = {}
        try:
            with self._init_db(path) as conn:
                cur = conn.cursor()
                placeholders = ",".join("?" for _ in table_names)
                cur.execute(f"""
                    SELECT object_id, object_name, row_count_estimate, description, fk_degree
                    FROM catalog_schema_object
                    WHERE fingerprint = ? AND object_name IN ({placeholders})
                """, [fingerprint] + list(table_names))
                obj_rows = cur.fetchall()
                if not obj_rows:
                    return {}

                for obj_id, obj_name, row_count, desc, fk_deg in obj_rows:
                    cur.execute("""
                        SELECT name, data_type, nullable, primary_key, is_foreign_key,
                               samples_json, date_range, distinct_estimate, null_fraction,
                               description, synonyms_json
                        FROM catalog_column
                        WHERE object_id = ?
                    """, (obj_id,))
                    col_rows = cur.fetchall()

                    cols = [
                        ColumnProfile(
                            name=c[0],
                            type=c[1],
                            nullable=bool(c[2]),
                            primary_key=bool(c[3]),
                            is_foreign_key=bool(c[4]),
                            samples=json.loads(c[5]) if c[5] else [],
                            date_range=c[6],
                            distinct_count=c[7],
                            null_fraction=c[8],
                            description=c[9],
                            synonyms=json.loads(c[10]) if c[10] else [],
                        )
                        for c in col_rows
                    ]

                    cur.execute("""
                        SELECT term FROM catalog_alias_term
                        WHERE canonical_id = ? AND entity_type = 'table'
                    """, (obj_id,))
                    synonyms = [r[0] for r in cur.fetchall()]

                    results[obj_name] = TableProfile(
                        name=obj_name,
                        columns=cols,
                        primary_key=[c.name for c in cols if c.primary_key],
                        foreign_keys=[],
                        indexes=[],
                        row_count=row_count,
                        fk_degree=fk_deg or 0,
                        profiled=row_count is not None,
                        description=desc,
                        synonyms=synonyms,
                    )
        except Exception as e:
            logger.warning("Error loading table subset (%s): %s", table_names, e)
        return results

    def _load_from_store(self, fingerprint: str) -> Optional[SchemaCatalog]:
        """Load from authoritative SystemStore first, falling back to local SQLite disk."""
        store_cat = system_store.load_normalized_catalog(fingerprint)
        if store_cat is not None and store_cat.tables:
            return store_cat
        return self._load_from_disk(fingerprint)

    def _load_from_disk(self, fingerprint: str) -> Optional[SchemaCatalog]:
        path = self._path_for(fingerprint)
        if not path.exists():
            return None
        try:
            with self._init_db(path) as conn:
                cur = conn.cursor()

                cur.execute("SELECT COUNT(*) FROM catalog_schema_object WHERE fingerprint = ?", (fingerprint,))
                norm_count = cur.fetchone()[0]

                if norm_count > 0:
                    # 1. Load connection
                    cur.execute("SELECT connection_id, database_name, tenant_id, dialect, fingerprint, version, last_introspected_at, last_profiled_at FROM catalog_database_connection WHERE fingerprint = ?", (fingerprint,))
                    conn_row = cur.fetchone()
                    conn_rec = DatabaseConnectionRecord(
                        connection_id=conn_row[0] if conn_row else f"conn_{fingerprint[:12]}",
                        database_name=conn_row[1] if conn_row and conn_row[1] else "Database",
                        tenant_id=conn_row[2] if conn_row else None,
                        dialect=conn_row[3] if conn_row else "sql",
                        fingerprint=fingerprint,
                        version=conn_row[5] if conn_row else "1.0",
                        last_introspected_at=conn_row[6] if conn_row else 0.0,
                        last_profiled_at=conn_row[7] if conn_row else None,
                    )

                    # 2. Load objects
                    cur.execute("SELECT object_id, fingerprint, schema_name, object_name, object_type, row_count_estimate, description, status, fk_degree FROM catalog_schema_object WHERE fingerprint = ?", (fingerprint,))
                    obj_rows = [
                        SchemaObjectRecord(
                            object_id=r[0], fingerprint=r[1], schema_name=r[2], object_name=r[3],
                            object_type=r[4], row_count_estimate=r[5], description=r[6], status=r[7], fk_degree=r[8] or 0
                        )
                        for r in cur.fetchall()
                    ]

                    # 3. Load columns
                    cur.execute("SELECT column_id, object_id, fingerprint, name, normalized_name, data_type, nullable, primary_key, is_foreign_key, semantic_type, description, synonyms_json, null_fraction, distinct_estimate, samples_json, date_range FROM catalog_column WHERE fingerprint = ?", (fingerprint,))
                    col_rows = [
                        ColumnRecord(
                            column_id=r[0], object_id=r[1], fingerprint=r[2], name=r[3], normalized_name=r[4],
                            data_type=r[5], nullable=bool(r[6]), primary_key=bool(r[7]), is_foreign_key=bool(r[8]),
                            semantic_type=r[9], description=r[10], synonyms=json.loads(r[11]) if r[11] else [],
                            null_fraction=r[12], distinct_estimate=r[13], samples=json.loads(r[14]) if r[14] else [],
                            date_range=r[15]
                        )
                        for r in cur.fetchall()
                    ]

                    # 4. Load relationships
                    cur.execute("SELECT relationship_id, fingerprint, source_object, source_column, target_object, target_column, relationship_type, confidence, source FROM catalog_relationship WHERE fingerprint = ?", (fingerprint,))
                    rel_rows = [
                        RelationshipRecord(
                            relationship_id=r[0], fingerprint=r[1], source_object=r[2], source_column=r[3],
                            target_object=r[4], target_column=r[5], relationship_type=r[6], confidence=r[7], source=r[8]
                        )
                        for r in cur.fetchall()
                    ]

                    # 5. Load indexes
                    cur.execute("SELECT index_id, object_id, fingerprint, index_name, columns_json, uniqueness, selectivity_hints FROM catalog_index_stats WHERE fingerprint = ?", (fingerprint,))
                    idx_rows = [
                        IndexStatsRecord(
                            index_id=r[0], object_id=r[1], fingerprint=r[2], index_name=r[3],
                            columns=json.loads(r[4]) if r[4] else [], uniqueness=bool(r[5]), selectivity_hints=r[6]
                        )
                        for r in cur.fetchall()
                    ]

                    # 6. Load aliases
                    cur.execute("SELECT alias_id, fingerprint, canonical_id, entity_type, term, language, source, confidence FROM catalog_alias_term WHERE fingerprint = ?", (fingerprint,))
                    alias_rows = [
                        AliasTermRecord(
                            alias_id=r[0], fingerprint=r[1], canonical_id=r[2], entity_type=r[3],
                            term=r[4], language=r[5], source=r[6], confidence=r[7]
                        )
                        for r in cur.fetchall()
                    ]

                    # 7. Load version
                    cur.execute("SELECT version_id, fingerprint, version, change_timestamp, build_status, job_id FROM catalog_version WHERE fingerprint = ?", (fingerprint,))
                    v_row = cur.fetchone()
                    v_rec = CatalogVersionRecord(
                        version_id=v_row[0], fingerprint=v_row[1], version=v_row[2],
                        change_timestamp=v_row[3], build_status=v_row[4], job_id=v_row[5]
                    ) if v_row else None

                    return SchemaCatalog.from_normalized_records(
                        connection=conn_rec,
                        objects=obj_rows,
                        columns=col_rows,
                        relationships=rel_rows,
                        indexes=idx_rows,
                        aliases=alias_rows,
                        version=v_rec,
                        built_at=conn_rec.last_introspected_at,
                    )

                # Fallback: Load from legacy tables
                cur.execute("SELECT key, value FROM metadata")
                meta = {row[0]: json.loads(row[1]) for row in cur.fetchall()}
                if not meta or meta.get("fingerprint") != fingerprint:
                    return None

                cur.execute("SELECT name, profile_json FROM tables")
                tables_data = {row[0]: json.loads(row[1]) for row in cur.fetchall()}
                full_data = {**meta, "tables": tables_data}
                return SchemaCatalog.from_dict(full_data)
        except Exception as e:
            logger.warning("Failed to load schema catalog from disk (%s): %s", path, e)
            return None

    def save(self, catalog: SchemaCatalog) -> None:
        """Persist SchemaCatalog to authoritative SystemStore and write local disk copy."""
        system_store.save_normalized_catalog(catalog)
        self._save_to_disk(catalog)

    def _save_to_disk(self, catalog: SchemaCatalog) -> None:
        path = self._path_for(catalog.fingerprint)
        try:
            norm_records = catalog.to_normalized_records()
            full_dict = catalog.to_dict()
            tables_dict = full_dict.pop("tables")

            with self._init_db(path) as conn:
                cur = conn.cursor()

                # 1. Save normalized DatabaseConnectionRecord
                for conn_rec in norm_records["connection"]:
                    cur.execute("""
                        INSERT OR REPLACE INTO catalog_database_connection (
                            connection_id, database_name, tenant_id, dialect, fingerprint, version, last_introspected_at, last_profiled_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        conn_rec.connection_id, conn_rec.database_name, conn_rec.tenant_id, conn_rec.dialect, conn_rec.fingerprint,
                        conn_rec.version, conn_rec.last_introspected_at, conn_rec.last_profiled_at
                    ))

                # 2. Save normalized SchemaObjectRecords
                obj_rows = [
                    (o.object_id, o.fingerprint, o.schema_name, o.object_name, o.object_type,
                     o.row_count_estimate, o.description, o.status, o.fk_degree)
                    for o in norm_records["objects"]
                ]
                cur.executemany("""
                    INSERT OR REPLACE INTO catalog_schema_object (
                        object_id, fingerprint, schema_name, object_name, object_type,
                        row_count_estimate, description, status, fk_degree
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, obj_rows)

                # 3. Save normalized ColumnRecords
                col_rows = [
                    (c.column_id, c.object_id, c.fingerprint, c.name, c.normalized_name,
                     c.data_type, int(c.nullable), int(c.primary_key), int(c.is_foreign_key),
                     c.semantic_type, c.description, json.dumps(c.synonyms),
                     c.null_fraction, c.distinct_estimate, json.dumps(c.samples), c.date_range)
                    for c in norm_records["columns"]
                ]
                cur.executemany("""
                    INSERT OR REPLACE INTO catalog_column (
                        column_id, object_id, fingerprint, name, normalized_name,
                        data_type, nullable, primary_key, is_foreign_key,
                        semantic_type, description, synonyms_json,
                        null_fraction, distinct_estimate, samples_json, date_range
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, col_rows)

                # 4. Save normalized RelationshipRecords
                rel_rows = [
                    (r.relationship_id, r.fingerprint, r.source_object, r.source_column,
                     r.target_object, r.target_column, r.relationship_type, r.confidence, r.source)
                    for r in norm_records["relationships"]
                ]
                cur.executemany("""
                    INSERT OR REPLACE INTO catalog_relationship (
                        relationship_id, fingerprint, source_object, source_column,
                        target_object, target_column, relationship_type, confidence, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, rel_rows)

                # 5. Save normalized IndexStatsRecords
                idx_rows = [
                    (i.index_id, i.object_id, i.fingerprint, i.index_name,
                     json.dumps(i.columns), int(i.uniqueness), i.selectivity_hints)
                    for i in norm_records["indexes"]
                ]
                cur.executemany("""
                    INSERT OR REPLACE INTO catalog_index_stats (
                        index_id, object_id, fingerprint, index_name,
                        columns_json, uniqueness, selectivity_hints
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, idx_rows)

                # 6. Save normalized AliasTermRecords
                alias_rows = [
                    (a.alias_id, a.fingerprint, a.canonical_id, a.entity_type,
                     a.term, a.language, a.source, a.confidence)
                    for a in norm_records["aliases"]
                ]
                cur.executemany("""
                    INSERT OR REPLACE INTO catalog_alias_term (
                        alias_id, fingerprint, canonical_id, entity_type,
                        term, language, source, confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, alias_rows)

                # 7. Save normalized CatalogVersionRecord
                for v_rec in norm_records["version"]:
                    cur.execute("""
                        INSERT OR REPLACE INTO catalog_version (
                            version_id, fingerprint, version, change_timestamp, build_status, job_id
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        v_rec.version_id, v_rec.fingerprint, v_rec.version,
                        v_rec.change_timestamp, v_rec.build_status, v_rec.job_id
                    ))

                # 8. Also write legacy metadata/tables for backward compatibility
                for k, v in full_dict.items():
                    cur.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (k, json.dumps(v)))
                table_rows = [(name, json.dumps(t_dict)) for name, t_dict in tables_dict.items()]
                cur.executemany("INSERT OR REPLACE INTO tables (name, profile_json) VALUES (?, ?)", table_rows)

                conn.commit()
        except Exception as e:
            logger.warning("Failed to persist schema catalog to SQLite disk (%s): %s", path, e)
