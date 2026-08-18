"""Builds and persists the Schema Catalog (Phase 1: profile once, reuse forever).

Why this exists
----------------
`SchemaService` (app/services/sql_service.py) already introspects the schema
and caches it in-process with a fingerprint+TTL. That solves *within-process*
repetition. It does not solve:

  1. Cold starts / multiple worker processes re-paying full introspection
     (including per-column sample-value queries) independently.
  2. Row counts / column cardinality, which are useful for grounding and for
     the LLM's prompt (e.g. "this table has 2M rows, don't SELECT *") but
     are not computed today.
  3. A place to attach a *business glossary* (human descriptions + synonyms)
     that only needs to be generated once per schema version and then reused
     for free on every future question, instead of asking the LLM to infer
     column meaning from scratch every single time.

`CatalogBuilder` wraps `SchemaService`, adds the missing structural facts,
and persists the result to disk as JSON keyed by the same DB fingerprint
`SchemaService` already computes — so a restart doesn't lose the profile,
and switching between two already-profiled databases is instant.
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

from app.config.settings import settings
from app.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile
from app.services.sql_service import SchemaService

# Where profiles are persisted. Overridable via env for deployments with a
# read-only container filesystem (point it at a mounted volume).
CATALOG_DIR = Path(settings.schema_catalog_dir)

from app.database.system_store import system_store

def set_build_progress(fingerprint: str, progress: dict):
    system_store.set_catalog_progress(fingerprint, progress)

def get_build_progress(fingerprint: str) -> dict:
    return system_store.get_catalog_progress(fingerprint)


class CatalogBuilder:
    """Builds a SchemaCatalog once per DB fingerprint and persists it to disk."""

    def __init__(self, schema_service: Optional[SchemaService] = None):
        self.schema_service = schema_service or SchemaService()
        CATALOG_DIR.mkdir(parents=True, exist_ok=True)

    # -- Public API ---------------------------------------------------

    def get_or_build(self, force_rebuild: bool = False) -> SchemaCatalog:
        """Return the catalog for the currently-connected database.

        Checks in-RAM DatabaseContext first (0ms), loads from SQLite disk if cached,
        or builds it if missing.
        """
        fingerprint = self.schema_service._get_db_fingerprint()
        from app.database.context import db_context_manager
        ctx = db_context_manager.get(fingerprint)

        if not force_rebuild:
            if ctx and ctx.catalog is not None:
                return ctx.catalog

            cached = self._load_from_disk(fingerprint)
            if cached is not None:
                if ctx is not None:
                    ctx.catalog = cached
                return cached

        catalog = self._build(fingerprint)
        self._save_to_disk(catalog)
        if ctx is not None:
            ctx.catalog = catalog
        return catalog

    def merge_glossary(self, catalog: SchemaCatalog, glossary: dict) -> SchemaCatalog:
        """Apply a glossary dict (see glossary.py) onto a catalog and persist it.

        glossary shape:
            {
              "tables": {"<table>": {"description": str, "synonyms": [str, ...]}},
              "columns": {"<table>.<column>": {"description": str, "synonyms": [str, ...]}}
            }
        """
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
        catalog.glossary_version += 1
        self._save_to_disk(catalog)
        return catalog

    async def enrich_with_embeddings(self, catalog: SchemaCatalog, force: bool = False) -> SchemaCatalog:
        """Phase 3: compute + persist table embeddings for semantic retrieval.

        Explicit, async, and never called from the hot question-answering
        path - same rule as `merge_glossary`. Best run right after
        `merge_glossary` so the embedded text includes the human
        descriptions/synonyms, not just raw column names.
        """
        from app.schema_catalog.embedding_retrieval import ensure_table_embeddings
        catalog = await ensure_table_embeddings(catalog, force=force)
        self._save_to_disk(catalog)
        return catalog

    async def build_async(self, fingerprint: str) -> None:
        """
        Background worker method to asynchronously profile rows and sample values for all tables.
        Updates `catalog_build_progress` globally so the UI can poll progress.
        Saves incrementally to disk.
        """
        import asyncio
        catalog = self._load_from_disk(fingerprint)
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
        
        # Batch size for incremental saves to disk
        save_batch_size = max(10, total_tables // 20)
        
        semaphore = asyncio.Semaphore(15)
        tables_processed = 0
        
        async def profile_single_table(tname):
            nonlocal tables_processed
            try:
                # schema_name might be embedded in tname (e.g., "public.users")
                parts = tname.split(".")
                schema_name = parts[0] if len(parts) > 1 else None
                base_table = parts[-1]
                
                tprof = catalog.tables[tname]
                
                # Construct target columns to avoid redundant inspector queries
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
                
                # Update the catalog table entry
                tprof.row_count = profile_data.get("row_count")
                
                col_updates = profile_data.get("columns", {})
                for col in tprof.columns:
                    if col.name in col_updates:
                        col.samples = col_updates[col.name].get("samples", [])
                        col.date_range = col_updates[col.name].get("date_range")
                        
            except Exception as e:
                logger.warning(f"Error profiling table {tname}: {e}")
                
            tables_processed += 1
            progress_percent = round((tables_processed / total_tables) * 100, 1)
            
            progress_state.update({
                "progress_percent": progress_percent,
                "tables_processed": tables_processed
            })
            set_build_progress(fingerprint, progress_state)

        # Process in chunks to avoid concurrent writes to SQLite and memory explosion
        for chunk_idx in range(0, total_tables, save_batch_size):
            chunk = tables[chunk_idx:chunk_idx + save_batch_size]
            tasks = [profile_single_table(tname) for tname in chunk]
            await asyncio.gather(*tasks)
            
            # Save the chunk synchronously via thread to prevent blocking
            await asyncio.to_thread(self._save_to_disk, catalog)
                
        progress_state["status"] = "complete"
        set_build_progress(fingerprint, progress_state)
        logger.info(f"Finished background data profile for {catalog.database_name}")

    # -- Building -------------------------------------------------------

    def _build(self, fingerprint: str) -> SchemaCatalog:
        t0 = time.time()
        raw_schema = self.schema_service.get_schema()  # reuses SchemaService's own introspection + sample values
        dialect = self.schema_service.get_database_type()
        db_name = self.schema_service.get_database_name()

        catalog = SchemaCatalog(fingerprint=fingerprint, dialect=dialect, database_name=db_name)

        # Foreign-key degree (join-graph centrality) — cheap, purely structural.
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
                    samples=[],  # Populated asynchronously in build_async
                    date_range=None, # Populated asynchronously in build_async
                )
                for c in info.get("columns", [])
            ]
            catalog.tables[tname] = TableProfile(
                name=tname,
                columns=columns,
                primary_key=info.get("primary_key", []),
                foreign_keys=info.get("foreign_keys", []),
                indexes=info.get("indexes", []),
                row_count=None,  # Populated asynchronously in build_async
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
                # Quick approximate row count from stats
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

    # -- Persistence ------------------------------------------------------

    def _path_for(self, fingerprint: str) -> Path:
        return CATALOG_DIR / f"{fingerprint}.db"

    def _init_db(self, path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS tables (name TEXT PRIMARY KEY, profile_json TEXT)")
        return conn

    def _load_from_disk(self, fingerprint: str) -> Optional[SchemaCatalog]:
        path = self._path_for(fingerprint)
        if not path.exists():
            return None
        try:
            with self._init_db(path) as conn:
                cur = conn.cursor()
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
        """Public wrapper around the disk-persistence step - for enrichment
        steps that live outside this class (e.g. Phase 5's schema-learning
        module) that need to persist a mutated catalog without duplicating
        the (private) storage format/path logic."""
        self._save_to_disk(catalog)

    def _save_to_disk(self, catalog: SchemaCatalog) -> None:
        path = self._path_for(catalog.fingerprint)
        try:
            full_dict = catalog.to_dict()
            tables_dict = full_dict.pop("tables")
            
            with self._init_db(path) as conn:
                cur = conn.cursor()
                # Upsert metadata
                for k, v in full_dict.items():
                    cur.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (k, json.dumps(v)))
                
                # Upsert tables (using chunking for large schemas to prevent locking)
                table_rows = [(name, json.dumps(t_dict)) for name, t_dict in tables_dict.items()]
                cur.executemany("INSERT OR REPLACE INTO tables (name, profile_json) VALUES (?, ?)", table_rows)
                conn.commit()
        except Exception as e:
            logger.warning("Failed to persist schema catalog to SQLite disk (%s): %s", path, e)
