import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from loguru import logger

from app.schema_grounding.relationship_graph import SchemaRelationshipGraph
from app.schema_catalog.models import SchemaCatalog
from app.schema_catalog.retrieval import TfidfTableRetriever


def compute_structural_schema_fingerprint(schema: Dict[str, Any]) -> str:
    """Compute a deterministic structural fingerprint for a custom schema dictionary.
    
    Includes sorted representations of:
    1. Table names
    2. Column names & types (sorted by column name)
    3. Primary key columns (sorted)
    4. Foreign key definitions (constrained_columns, referred_schema, referred_table, referred_columns)
    5. Index definitions (name, columns, unique)
    
    Insensitive to Python dict insertion order.
    """
    if not schema:
        return "custom_schema_empty"

    normalized_tables = []
    for table_name in sorted(schema.keys()):
        info = schema[table_name] or {}
        
        # Normalize columns
        raw_cols = info.get("columns", [])
        norm_cols = sorted([
            {
                "name": str(c.get("name", "")),
                "type": str(c.get("type", "")),
            }
            for c in raw_cols if isinstance(c, dict)
        ], key=lambda x: x["name"])
        
        # Normalize primary key
        raw_pk = info.get("primary_key", [])
        norm_pk = sorted([str(col) for col in raw_pk])
        
        # Normalize foreign keys
        raw_fks = info.get("foreign_keys", [])
        norm_fks = sorted([
            {
                "constrained_columns": sorted([str(col) for col in fk.get("constrained_columns", [])]),
                "referred_schema": str(fk.get("referred_schema")) if fk.get("referred_schema") else None,
                "referred_table": str(fk.get("referred_table")) if fk.get("referred_table") else "",
                "referred_columns": sorted([str(col) for col in fk.get("referred_columns", [])]),
            }
            for fk in raw_fks if isinstance(fk, dict)
        ], key=lambda x: (x["referred_table"], ",".join(x["constrained_columns"])))
        
        # Normalize indexes
        raw_idxs = info.get("indexes", [])
        norm_idxs = sorted([
            {
                "name": str(idx.get("name", "")),
                "columns": sorted([str(col) for col in idx.get("columns", [])]),
                "unique": bool(idx.get("unique", False)),
            }
            for idx in raw_idxs if isinstance(idx, dict)
        ], key=lambda x: x["name"])
        
        normalized_tables.append({
            "table": str(table_name),
            "columns": norm_cols,
            "primary_key": norm_pk,
            "foreign_keys": norm_fks,
            "indexes": norm_idxs,
        })
        
    normalized_json = json.dumps(normalized_tables, sort_keys=True)
    digest = hashlib.sha256(normalized_json.encode("utf-8")).hexdigest()
    return f"custom_schema_{digest[:16]}"


@dataclass
class SchemaIntelligenceBundle:
    """Holds immutable, schema-derived intelligence structures keyed by database fingerprint."""
    fingerprint: str
    relationship_graph: SchemaRelationshipGraph
    tfidf_retriever: Optional[TfidfTableRetriever]
    created_at: float
    table_count: int


class SchemaIntelligenceCache:
    """Thread-safe, fingerprint-keyed in-memory cache for schema intelligence bundles."""

    _lock = threading.RLock()
    _cache_store: Dict[str, SchemaIntelligenceBundle] = {}

    @classmethod
    def get_or_build(
        cls,
        fingerprint: str,
        schema: Dict[str, Any],
        catalog: Optional[SchemaCatalog] = None,
    ) -> Tuple[SchemaIntelligenceBundle, bool, float, float]:
        """Return (bundle, cache_hit, lookup_ms, build_ms).
        
        Uses double-checked locking to ensure single construction under concurrent requests.
        """
        t0 = time.perf_counter()
        
        with cls._lock:
            bundle = cls._cache_store.get(fingerprint)
            if bundle is not None:
                lookup_ms = (time.perf_counter() - t0) * 1000
                return bundle, True, lookup_ms, 0.0

            # Check if DatabaseContext in RAM already holds the pre-built graph
            try:
                from app.database.context import db_context_manager
                ctx = db_context_manager.get(fingerprint)
                if ctx and ctx.relationship_graph is not None:
                    bundle = SchemaIntelligenceBundle(
                        fingerprint=fingerprint,
                        relationship_graph=ctx.relationship_graph,
                        tfidf_retriever=ctx.tfidf_retriever,
                        created_at=ctx.created_at,
                        table_count=len(schema),
                    )
                    cls._cache_store[fingerprint] = bundle
                    lookup_ms = (time.perf_counter() - t0) * 1000
                    return bundle, True, lookup_ms, 0.0
            except Exception:
                pass

            # Double-checked locking pattern for cache miss
            t_build_start = time.perf_counter()
            rel_graph = SchemaRelationshipGraph(schema)
            tfidf_retriever = None
            if catalog is not None and catalog.tables:
                try:
                    tfidf_retriever = TfidfTableRetriever(catalog)
                except Exception as e:
                    logger.debug("Failed to build TfidfTableRetriever for intelligence bundle: %s", e)

            bundle = SchemaIntelligenceBundle(
                fingerprint=fingerprint,
                relationship_graph=rel_graph,
                tfidf_retriever=tfidf_retriever,
                created_at=time.time(),
                table_count=len(schema),
            )
            cls._cache_store[fingerprint] = bundle
            build_ms = (time.perf_counter() - t_build_start) * 1000
            lookup_ms = (time.perf_counter() - t0) * 1000
            return bundle, False, lookup_ms, build_ms

    @classmethod
    def clear(cls, fingerprint: Optional[str] = None) -> None:
        """Explicitly invalidate cached intelligence bundle(s)."""
        with cls._lock:
            if fingerprint:
                cls._cache_store.pop(fingerprint, None)
            else:
                cls._cache_store.clear()
