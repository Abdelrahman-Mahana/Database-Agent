"""Persistent In-Memory DatabaseContext per database fingerprint.

Provides an in-RAM Single Source of Truth for:
- Connection engine and sessionmaker
- Parsed full schema, light schema, and schema text
- Explorer data (tables, views, procedures, tree, summary)
- Starter / recommended questions
- Schema Relationship Graph (FK join paths)
- Table / Column search index (TF-IDF retriever)
- Persisted SchemaCatalog (business glossary & learned corrections)

Eliminates repetitive SQLite disk reads and JSON deserialization on every request.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import structlog
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config.settings import settings

logger = structlog.get_logger(__name__)


def compute_db_fingerprint(engine_or_url: str | Engine) -> str:
    """Generate a deterministic fingerprint based on database identity and file state."""
    if isinstance(engine_or_url, Engine):
        url_str = str(engine_or_url.url)
        db_path = getattr(engine_or_url.url, "database", None)
    else:
        url_str = str(engine_or_url)
        db_path = None
        if url_str.startswith("sqlite:///"):
            db_path = url_str[len("sqlite:///"):]

    extra = ""
    # If SQLite file database, append file mtime and size to auto-detect schema updates on disk
    if url_str.startswith("sqlite") and db_path:
        if os.path.exists(db_path):
            try:
                stat = os.stat(db_path)
                extra = f":mtime={stat.st_mtime}:size={stat.st_size}"
            except Exception:
                pass
    raw_key = f"{url_str}{extra}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


@dataclass
class DatabaseContext:
    """Holds all active in-RAM context for a specific database fingerprint."""

    fingerprint: str
    url: str
    dialect: str = "sql"
    database_name: str = "Database"
    engine: Optional[Engine] = None
    sessionmaker: Optional[sessionmaker] = None

    # Schema Metadata
    schema: Dict[str, Any] = field(default_factory=dict)
    schema_text: str = ""
    light_schema: Dict[str, Any] = field(default_factory=dict)
    explorer_data: Dict[str, Any] = field(default_factory=dict)
    recommended_questions: List[Dict[str, Any]] = field(default_factory=list)

    # Intelligence & Navigation
    catalog: Optional[Any] = None  # SchemaCatalog
    relationship_graph: Optional[Any] = None  # SchemaRelationshipGraph
    tfidf_retriever: Optional[Any] = None  # TfidfTableRetriever
    embedding_retriever: Optional[Any] = None  # EmbeddingTableRetriever
    keyword_to_tables: Dict[str, Set[str]] = field(default_factory=dict)
    table_names_set: Set[str] = field(default_factory=set)
    total_tables: int = 0
    total_columns: int = 0
    indexes_built: bool = False

    # Lifecycle & Caching
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)
    ttl: int = 3600

    def is_expired(self, ttl: Optional[int] = None) -> bool:
        """Check if context has expired based on TTL."""
        check_ttl = self.ttl if ttl is None else ttl
        if check_ttl <= 0:
            return False
        return (time.time() - self.created_at) > check_ttl

    def touch(self) -> None:
        """Update last accessed timestamp."""
        self.last_accessed_at = time.time()

    def get_table_summary(self) -> str:
        """Return a compact one-line summary of tables in the database."""
        if not self.table_names_set and self.schema:
            self.table_names_set = set(self.schema.keys())
        return ", ".join(sorted(self.table_names_set))

    def ensure_indexes(self, force: bool = False) -> None:
        """
        Prepare catalog, join graph, TF-IDF retriever, embedding retriever,
        and inverted keyword index ONCE ahead of time in RAM.
        """
        if self.indexes_built and not force:
            return

        # 1. Join Graph
        if self.schema and (self.relationship_graph is None or force):
            try:
                from app.schema_grounding.relationship_graph import SchemaRelationshipGraph
                self.relationship_graph = SchemaRelationshipGraph(self.schema)
            except Exception as e:
                logger.debug("Failed to build relationship_graph in DatabaseContext: %s", e)

        # 2. Schema Catalog
        if (self.catalog is None or force) and self.fingerprint:
            try:
                from app.schema_catalog.catalog_builder import CatalogBuilder
                from app.services.sql_service import SchemaService
                service = SchemaService(bind_engine=self.engine)
                cb = CatalogBuilder(schema_service=service)
                self.catalog = cb.get_or_build(force_rebuild=force)
            except Exception as e:
                logger.debug("Failed to load catalog into DatabaseContext: %s", e)

        # 3. TF-IDF & Embedding Retrievers
        if self.catalog is not None and getattr(self.catalog, "tables", None):
            try:
                from app.schema_catalog.retrieval import TfidfTableRetriever
                self.tfidf_retriever = TfidfTableRetriever(self.catalog)
            except Exception as e:
                logger.debug("Failed to build tfidf_retriever in DatabaseContext: %s", e)

            if getattr(self.catalog, "embeddings_built", False):
                try:
                    from app.schema_catalog.embedding_retrieval import EmbeddingTableRetriever
                    self.embedding_retriever = EmbeddingTableRetriever(self.catalog)
                except Exception as e:
                    logger.debug("Failed to build embedding_retriever in DatabaseContext: %s", e)

        # 4. Inverted Keyword Index (for 0ms seed table matching)
        if self.schema and (not self.keyword_to_tables or force):
            kw_map: Dict[str, Set[str]] = {}
            for table_name, info in self.schema.items():
                t_lower = table_name.lower()
                # Table variations
                variations = {
                    t_lower,
                    t_lower + "s",
                    t_lower + "es",
                }
                if t_lower.endswith("y"):
                    variations.add(t_lower[:-1] + "ies")
                if t_lower.endswith("s") and not t_lower.endswith("ss"):
                    variations.add(t_lower[:-1])
                if t_lower.endswith("es"):
                    variations.add(t_lower[:-2])
                if t_lower.endswith("ies"):
                    variations.add(t_lower[:-3] + "y")

                for v in variations:
                    if len(v) > 2:
                        kw_map.setdefault(v, set()).add(table_name)

                # Column names
                for col in info.get("columns", []):
                    c_lower = col["name"].lower()
                    if len(c_lower) >= 3:
                        kw_map.setdefault(c_lower, set()).add(table_name)

            # Business glossary synonyms if available
            if self.catalog and getattr(self.catalog, "tables", None):
                for tname, prof in self.catalog.tables.items():
                    for syn in prof.synonyms:
                        syn_l = syn.strip().lower()
                        if len(syn_l) > 2:
                            kw_map.setdefault(syn_l, set()).add(tname)
                    for col in prof.columns:
                        for syn in col.synonyms:
                            syn_l = syn.strip().lower()
                            if len(syn_l) > 2:
                                kw_map.setdefault(syn_l, set()).add(tname)

            self.keyword_to_tables = kw_map

        if not self.table_names_set and self.schema:
            self.table_names_set = set(self.schema.keys())

        if self.schema:
            self.total_tables = len(self.schema)
            self.total_columns = sum(len(info.get("columns", [])) for info in self.schema.values())

        self.indexes_built = True

    def match_seed_tables_fast(self, text: str, max_tables: int = 15) -> Set[str]:
        """Fast 0ms token-lookup against the pre-computed inverted keyword index."""
        if not self.keyword_to_tables:
            self.ensure_indexes()

        import re
        tokens = set(re.findall(r'[\w\u0600-\u06FF]+', text.lower()))
        matched: Set[str] = set()
        for token in tokens:
            if token in self.keyword_to_tables:
                matched.update(self.keyword_to_tables[token])
                if len(matched) >= max_tables:
                    break
        return matched


class DatabaseContextManager:
    """Thread-safe LRU manager holding active DatabaseContext instances in RAM."""

    def __init__(self, capacity: int = 50):
        self.capacity = capacity
        self._contexts: OrderedDict[str, DatabaseContext] = OrderedDict()
        self._lock = threading.RLock()

    def get(self, fingerprint: str) -> Optional[DatabaseContext]:
        """Retrieve a DatabaseContext from RAM by fingerprint."""
        with self._lock:
            if fingerprint in self._contexts:
                ctx = self._contexts[fingerprint]
                if ctx.is_expired():
                    logger.info("DatabaseContext expired in RAM", fingerprint=fingerprint[:12])
                    self._contexts.pop(fingerprint, None)
                    return None
                ctx.touch()
                self._contexts.move_to_end(fingerprint)
                return ctx
            return None

    def set(self, fingerprint: str, context: DatabaseContext) -> None:
        """Store a DatabaseContext in RAM with LRU capacity enforcement."""
        with self._lock:
            if fingerprint in self._contexts:
                self._contexts.move_to_end(fingerprint)
            self._contexts[fingerprint] = context

            # Enforce LRU capacity limit
            while len(self._contexts) > self.capacity:
                oldest_fp, oldest_ctx = self._contexts.popitem(last=False)
                logger.info("Evicting oldest DatabaseContext from RAM", fingerprint=oldest_fp[:12])
                try:
                    if oldest_ctx.engine:
                        oldest_ctx.engine.dispose()
                except Exception as e:
                    logger.warning("Error disposing engine on context eviction", error=str(e))

    def invalidate(self, fingerprint: str) -> None:
        """Explicitly remove a DatabaseContext from RAM."""
        with self._lock:
            ctx = self._contexts.pop(fingerprint, None)
            if ctx:
                logger.info("Invalidated DatabaseContext from RAM", fingerprint=fingerprint[:12])
                try:
                    if ctx.engine:
                        ctx.engine.dispose()
                except Exception as e:
                    logger.warning("Error disposing engine on invalidation", error=str(e))

    def clear(self) -> None:
        """Clear all active contexts from RAM."""
        with self._lock:
            for fp, ctx in list(self._contexts.items()):
                try:
                    if ctx.engine:
                        ctx.engine.dispose()
                except Exception:
                    pass
            self._contexts.clear()
            logger.info("Cleared all DatabaseContexts from RAM")

    def count(self) -> int:
        """Return the number of cached database contexts currently in RAM."""
        with self._lock:
            return len(self._contexts)


# Global singleton instance of DatabaseContextManager
db_context_manager = DatabaseContextManager(capacity=50)
