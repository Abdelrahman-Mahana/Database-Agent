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

from app.core.config.settings import settings

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
    """Holds ephemeral in-worker RAM cache (L1) for a specific database fingerprint.

    Authoritative metadata is persisted in SystemStore. DatabaseContext serves solely
    as a fast, in-memory worker accelerator for:
    - Connection engine and sessionmaker
    - Parsed schema text and structure
    - Schema Relationship Graph (FK join paths)
    - TF-IDF and Embedding search retrievers
    - Fast inverted keyword index
    """

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
    catalog_version: int = 0
    catalog_loaded_at: float = 0.0
    relationship_graph: Optional[Any] = None  # SchemaRelationshipGraph
    tfidf_retriever: Optional[Any] = None  # TfidfTableRetriever
    embedding_retriever: Optional[Any] = None  # EmbeddingTableRetriever
    alias_index: Optional[Any] = None  # AliasIndex
    candidate_retriever: Optional[Any] = None  # HybridCandidateRetriever
    keyword_to_tables: Dict[str, Set[str]] = field(default_factory=dict)
    table_names_set: Set[str] = field(default_factory=set)
    total_tables: int = 0
    total_columns: int = 0
    indexes_built: bool = False
    _indexing: bool = field(default=False, repr=False, compare=False)

    # Lifecycle & Caching
    created_at: float = field(default_factory=time.time)
    last_accessed_at: float = field(default_factory=time.time)
    ttl: int = 3600
    _semantic_version: Optional[str] = field(default=None, repr=False)

    def get_semantic_version(self) -> str:
        """Return deterministic semantic & schema version hash combining structure and catalog."""
        if self._semantic_version is not None:
            return self._semantic_version

        import json
        struct_summary = []
        if self.schema:
            for t_name in sorted(self.schema.keys()):
                t_info = self.schema[t_name] or {}
                cols = t_info.get("columns", [])
                cols_sig = [f"{c.get('name')}:{c.get('type')}:{c.get('primary_key', False)}" for c in cols if isinstance(c, dict)]
                fks = t_info.get("foreign_keys", [])
                fks_sig = [f"{fk.get('constrained_columns')}->{fk.get('referred_table')}.{fk.get('referred_columns')}" for fk in fks if isinstance(fk, dict)]
                struct_summary.append(f"{t_name}({','.join(cols_sig)})[FK:{','.join(fks_sig)}]")

        cat_ver = self.catalog_version or (getattr(self.catalog, "glossary_version", 0) if self.catalog else 0)
        cat_hash = ""
        if self.catalog:
            try:
                glossary = getattr(self.catalog, "business_glossary", {})
                if glossary:
                    cat_hash = hashlib.sha256(json.dumps(glossary, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
            except Exception:
                pass

        raw_str = f"{self.fingerprint}:dialect={self.dialect}:cat_v={cat_ver}:cat_h={cat_hash}:struct={'|'.join(struct_summary)}"
        self._semantic_version = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
        return self._semantic_version

    def invalidate_semantic_version(self) -> None:
        """Reset cached semantic version token."""
        self._semantic_version = None

    def is_expired(self, ttl: Optional[int] = None) -> bool:
        """Check if context has expired based on TTL."""
        check_ttl = self.ttl if ttl is None else ttl
        if check_ttl <= 0:
            return False
        return (time.time() - self.created_at) > check_ttl

    def touch(self) -> None:
        """Update last accessed timestamp."""
        self.last_accessed_at = time.time()

    def is_stale_against_version(self, authoritative_version: int) -> bool:
        """Check if this worker's cached catalog is behind authoritative persistent storage."""
        return authoritative_version > self.catalog_version

    def rehydrate_catalog_if_stale(self) -> bool:
        """Check authoritative store and rehydrate in-RAM catalog and indexes if stale."""
        try:
            from app.services.database.system_store import system_store
            latest = system_store.get_latest_catalog_version(self.fingerprint)
            if latest and self.is_stale_against_version(latest.version):
                logger.info(
                    "DatabaseContext is stale (cached v%s vs authoritative store v%s), rehydrating",
                    self.catalog_version, latest.version
                )
                from app.models.schema_catalog.catalog_builder import CatalogBuilder
                from app.services.sql_service import SchemaService
                service = SchemaService(bind_engine=self.engine)
                cb = CatalogBuilder(schema_service=service)
                cat = cb._load_from_store(self.fingerprint)
                if cat:
                    self.catalog = cat
                    self.catalog_version = getattr(cat, "glossary_version", latest.version)
                    self.catalog_loaded_at = time.time()
                    self.indexes_built = False
                    self.invalidate_semantic_version()
                    self.ensure_indexes(force=False)
                    return True
        except Exception as e:
            logger.debug("Error checking catalog freshness in DatabaseContext: %s", e)
        return False

    def get_table_summary(self) -> str:
        """Return a compact one-line summary of tables in the database."""
        if not self.table_names_set and self.schema:
            self.table_names_set = set(self.schema.keys())
        return ", ".join(sorted(self.table_names_set))

    @property
    def compact_summary(self) -> str:
        """Token-efficient database overview (~1 line per table, table name + column count)."""
        if not self.schema:
            return "No schema loaded."
        lines = [f"Database: {self.database_name} ({self.total_tables} tables, {self.total_columns} columns)"]
        for tname in sorted(self.schema.keys()):
            n_cols = len(self.schema[tname].get("columns", []))
            lines.append(f"  {tname} ({n_cols} cols)")
        return "\n".join(lines)

    def ensure_indexes(self, force: bool = False) -> None:
        """
        Prepare catalog, join graph, TF-IDF retriever, embedding retriever,
        and inverted keyword index ONCE ahead of time in RAM.
        """
        if (self.indexes_built and not force) or self._indexing:
            return

        self._indexing = True
        try:
            # 1. Join Graph
            if self.schema and (self.relationship_graph is None or force):
                try:
                    from app.agent.schema_grounding.relationship_graph import SchemaRelationshipGraph
                    self.relationship_graph = SchemaRelationshipGraph(self.schema)
                except Exception as e:
                    logger.debug("Failed to build relationship_graph in DatabaseContext: %s", e)

            # 2. Schema Catalog
            if (self.catalog is None or force) and self.fingerprint:
                try:
                    from app.models.schema_catalog.catalog_builder import CatalogBuilder
                    from app.services.sql_service import SchemaService
                    service = SchemaService(bind_engine=self.engine)
                    cb = CatalogBuilder(schema_service=service)
                    if self.catalog is None:
                        self.catalog = cb.get_or_build(force_rebuild=force, raw_schema=self.schema)
                except Exception as e:
                    logger.debug("Failed to load catalog into DatabaseContext: %s", e)

            if self.catalog:
                self.catalog_version = getattr(self.catalog, "glossary_version", 0)
                self.catalog_loaded_at = time.time()

            # 3. TF-IDF, Embedding, Alias, and Hybrid Candidate Retrievers
            if self.catalog is not None and getattr(self.catalog, "tables", None):
                try:
                    from app.models.schema_catalog.retrieval import TfidfTableRetriever, AliasIndex, HybridCandidateRetriever
                    self.tfidf_retriever = TfidfTableRetriever(self.catalog)
                    self.alias_index = AliasIndex(self.catalog)
                except Exception as e:
                    logger.debug("Failed to build tfidf_retriever or alias_index in DatabaseContext: %s", e)

                if getattr(self.catalog, "embeddings_built", False):
                    try:
                        from app.models.schema_catalog.embedding_retrieval import EmbeddingTableRetriever
                        self.embedding_retriever = EmbeddingTableRetriever(self.catalog)
                    except Exception as e:
                        logger.debug("Failed to build embedding_retriever in DatabaseContext: %s", e)

                try:
                    from app.models.schema_catalog.retrieval import HybridCandidateRetriever
                    self.candidate_retriever = HybridCandidateRetriever(
                        catalog=self.catalog,
                        tfidf_retriever=self.tfidf_retriever,
                        embedding_retriever=self.embedding_retriever,
                        alias_index=self.alias_index,
                    )
                except Exception as e:
                    logger.debug("Failed to build candidate_retriever in DatabaseContext: %s", e)

            # 4. Inverted Keyword Index (for 0ms seed table matching)
            if self.schema and (not self.keyword_to_tables or force):
                kw_map: Dict[str, Set[str]] = {}

                def add_variations(term: str, table_name: str) -> None:
                    term = term.lower().strip('"')
                    if not term:
                        return
                    variations = {
                        term,
                        term + "s",
                        term + "es",
                    }
                    if term.endswith("y"):
                        variations.add(term[:-1] + "ies")
                    if term.endswith("s") and not term.endswith("ss"):
                        variations.add(term[:-1])
                    if term.endswith("es"):
                        variations.add(term[:-2])
                    if term.endswith("ies"):
                        variations.add(term[:-3] + "y")

                    for v in variations:
                        if len(v) > 2:
                            kw_map.setdefault(v, set()).add(table_name)

                for table_name, info in self.schema.items():
                    t_lower = table_name.lower()
                    bare_table = t_lower.rsplit(".", 1)[-1]

                    # Table variations: qualified name, bare name, and useful
                    # underscore-separated business tokens (res_company -> company).
                    add_variations(t_lower, table_name)
                    add_variations(bare_table, table_name)
                    for part in bare_table.split("_"):
                        if part not in {"rel", "res", "ir", "hr", "crm", "ivf", "opd"}:
                            add_variations(part, table_name)

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

                # Core Business & ERP Domain Synonyms (Arabic + English)
                DOMAIN_SYNONYMS = [
                    (
                        {"invoice", "invoices", "bill", "bills", "billing", "فاتورة", "فواتير", "الفاتورة", "الفواتير"},
                        {"account_move", "account_move_line", "account_invoice", "inpatient_invoice"}
                    ),
                    (
                        {"sales", "sale", "revenue", "income", "مبيعات", "المبيعات", "إيرادات", "الايرادات", "ارباح", "أرباح", "ربح"},
                        {"account_move", "account_move_line", "sale_order", "sale_order_line"}
                    ),
                    (
                        {"customer", "customers", "client", "clients", "partner", "partners", "عميل", "عملاء", "العميل", "العملاء", "زبون", "زبائن", "شركاء", "شريك"},
                        {"res_partner"}
                    ),
                    (
                        {"doctor", "doctors", "physician", "physicians", "طبيب", "أطباء", "اطباء", "الأطباء", "دكتور", "دكاترة"},
                        {"doctor_model", "res_partner"}
                    ),
                    (
                        {"patient", "patients", "مريض", "مرضى", "المرضى"},
                        {"patient_model", "res_partner"}
                    ),
                    (
                        {"product", "products", "item", "items", "medicine", "medicines", "drugs", "منتج", "منتجات", "المنتجات", "أدوية", "دواء", "أصناف", "صنف"},
                        {"product_template", "product_product"}
                    ),
                    (
                        {"booking", "bookings", "reservation", "reservations", "حجز", "حجوزات", "الحجوزات"},
                        {"booking_model", "reservation_model"}
                    ),
                    (
                        {"doctor_services", "doctor_services_model", "doctor services", "خدمات الأطباء", "خدمات الاطباء"},
                        {"doctor_services_model"}
                    ),
                    (
                        {"company", "companies", "شركة", "شركات", "الشركات"},
                        {"res_company"}
                    ),
                    (
                        {"payment", "payments", "سداد", "دفعات", "مدفوعات", "المدفوعات"},
                        {"account_payment", "account_move"}
                    ),
                ]
                for synonyms, target_bare_names in DOMAIN_SYNONYMS:
                    for target in target_bare_names:
                        for tname in self.schema.keys():
                            bare = tname.lower().split(".")[-1].strip('"')
                            if bare == target or target in bare:
                                for syn in synonyms:
                                    syn_clean = syn.lower().strip()
                                    kw_map.setdefault(syn_clean, set()).add(tname)

                self.keyword_to_tables = kw_map

            if not self.table_names_set and self.schema:
                self.table_names_set = set(self.schema.keys())

            if self.schema:
                self.total_tables = len(self.schema)
                self.total_columns = sum(len(info.get("columns", [])) for info in self.schema.values())

            self.indexes_built = True
        finally:
            self._indexing = False

    def match_seed_tables_fast(self, text: str, max_tables: int = 15) -> Set[str]:
        """Fast 0ms token-lookup against the pre-computed inverted keyword index."""
        if not self.keyword_to_tables:
            self.ensure_indexes()

        import re
        ignored_tokens = {
            "id", "ids", "first", "last", "top", "list", "show", "get",
            "find", "records", "rows", "data", "database", "table", "tables",
        }
        clean_text = re.sub(r'[؟،؛ـ!?.,:;\'"()\[\]{}`]', ' ', text.lower())
        tokens = {
            token for token in re.findall(r'[a-zA-Z0-9_\u0621-\u064A]+', clean_text)
            if token not in ignored_tokens
        }
        matched_scores: Dict[str, float] = {}
        for token in tokens:
            if token in self.keyword_to_tables:
                for table_name in self.keyword_to_tables[token]:
                    bare_table = table_name.lower().rsplit(".", 1)[-1]
                    singular_token = token[:-3] + "y" if token.endswith("ies") else (
                        token[:-1] if token.endswith("s") and len(token) > 3 else token
                    )
                    score = 1.0
                    if token == bare_table or singular_token == bare_table:
                        score += 3.0
                    elif (
                        bare_table.endswith("_" + token)
                        or bare_table.startswith(token + "_")
                        or bare_table.endswith("_" + singular_token)
                        or bare_table.startswith(singular_token + "_")
                    ):
                        score += 2.0
                    elif token in bare_table.split("_") or singular_token in bare_table.split("_"):
                        score += 1.0
                    matched_scores[table_name] = matched_scores.get(table_name, 0.0) + score

        ordered = sorted(matched_scores, key=lambda t: (-matched_scores[t], t))
        return set(ordered[:max_tables])


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
