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
import time
from pathlib import Path
from typing import Optional

from loguru import logger
from sqlalchemy import text

from app.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile
from app.services.sql_service import SchemaService

# Where profiles are persisted. Overridable via env for deployments with a
# read-only container filesystem (point it at a mounted volume).
CATALOG_DIR = Path(os.getenv("SCHEMA_CATALOG_DIR", Path(__file__).resolve().parents[2] / "data" / "schema_catalog"))

# Row-count / cardinality probes are best-effort and must never block the
# main request path for long — cap their cost on large production tables.
ROW_COUNT_TIMEOUT_TABLES_MAX = 500  # skip row counts entirely on absurdly wide schemas


class CatalogBuilder:
    """Builds a SchemaCatalog once per DB fingerprint and persists it to disk."""

    def __init__(self, schema_service: Optional[SchemaService] = None):
        self.schema_service = schema_service or SchemaService()
        CATALOG_DIR.mkdir(parents=True, exist_ok=True)

    # -- Public API ---------------------------------------------------

    def get_or_build(self, force_rebuild: bool = False) -> SchemaCatalog:
        """Return the catalog for the currently-connected database.

        Loads from disk if a profile for the current fingerprint already
        exists; otherwise builds it (structural profiling only — the
        glossary/synonym enrichment is a separate, explicit, LLM-backed step
        so it never happens implicitly inside a hot request path).
        """
        fingerprint = self.schema_service._get_db_fingerprint()
        if not force_rebuild:
            cached = self._load_from_disk(fingerprint)
            if cached is not None:
                return cached

        catalog = self._build(fingerprint)
        self._save_to_disk(catalog)
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

        compute_row_counts = len(raw_schema) <= ROW_COUNT_TIMEOUT_TABLES_MAX

        for tname, info in raw_schema.items():
            fk_cols = {c for fk in info.get("foreign_keys", []) for c in fk.get("constrained_columns", [])}
            columns = [
                ColumnProfile(
                    name=c["name"],
                    type=c["type"],
                    nullable=c.get("nullable", True),
                    primary_key=c.get("primary_key", False),
                    is_foreign_key=c["name"] in fk_cols,
                    samples=c.get("samples", []) or [],
                    date_range=c.get("date_range"),
                )
                for c in info.get("columns", [])
            ]
            row_count = self._safe_row_count(tname) if compute_row_counts else None
            catalog.tables[tname] = TableProfile(
                name=tname,
                columns=columns,
                primary_key=info.get("primary_key", []),
                foreign_keys=info.get("foreign_keys", []),
                indexes=info.get("indexes", []),
                row_count=row_count,
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
            prep = self.schema_service.inspector.dialect.identifier_preparer
            quoted = prep.quote(table_name)
            with self.schema_service.engine.connect() as conn:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {quoted}"))
                row = result.fetchone()
            return int(row[0]) if row else None
        except Exception:
            return None

    # -- Persistence ------------------------------------------------------

    def _path_for(self, fingerprint: str) -> Path:
        return CATALOG_DIR / f"{fingerprint}.json"

    def _load_from_disk(self, fingerprint: str) -> Optional[SchemaCatalog]:
        path = self._path_for(fingerprint)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("fingerprint") != fingerprint:
                return None
            return SchemaCatalog.from_dict(data)
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
            tmp_path = path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(catalog.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, path)
        except Exception as e:
            logger.warning("Failed to persist schema catalog to disk (%s): %s", path, e)
