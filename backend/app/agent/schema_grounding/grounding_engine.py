

"""Schema Grounding Engine — discovers minimal required schema subsets and join paths."""
import re
import time
from typing import Any, Dict, Optional, Set

from loguru import logger

from app.services.sql_service import SchemaService
from app.agent.semantic.models import QueryUnderstanding
from app.agent.schema_grounding.models import GroundedSchema
from app.agent.schema_grounding.schema_intelligence import (
    SchemaIntelligenceCache,
    compute_structural_schema_fingerprint,
)
from app.agent.schema_grounding.relationship_graph import SchemaRelationshipGraph
from app.agent.schema_grounding.schema_pruner import SchemaPruner
from app.utils.text_processor import AnalysisType, COMPLEX_ANALYSIS_TYPES
from app.agent.schema_grounding.arabic_terms import expand_with_arabic_terms
from app.models.schema_catalog.models import SchemaCatalog
from app.models.schema_catalog.retrieval import retrieve_relevant_tables, retrieve_relevant_tables_async
from app.core.config.settings import settings

_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "for", "and", "or", "to", "is", "are",
    "table", "column", "data", "how", "many", "what", "show", "list", "get", "find",
    "exist", "database", "system", "all", "total", "count",
}

# COMPARISON/RANKING questions frequently name only one side of a metric
_NEEDS_NEIGHBOR_EXPANSION = COMPLEX_ANALYSIS_TYPES | {AnalysisType.RANKING}

_NUMERIC_TYPE_MARKERS = ("INT", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL", "REAL", "MONEY")
_ID_NAME_MARKERS = ("id", "_id", "code", "key")


def _has_metric_column(table_info: Dict[str, Any]) -> bool:
    """True if a table has at least one numeric column that isn't just an ID/FK."""
    for col in table_info.get("columns", []):
        col_type = (col.get("type") or "").upper()
        col_name = (col.get("name") or "").lower()
        if any(m in col_type for m in _NUMERIC_TYPE_MARKERS) and not any(
            m in col_name for m in _ID_NAME_MARKERS
        ):
            return True
    return False


class SchemaGroundingEngine:
    """
    Deterministic Schema Grounding Engine.
    Selects only the minimal relevant subset of the database schema required
    for SQL generation based on QueryUnderstanding semantic entities.
    """

    def __init__(self, schema_service: Optional[SchemaService] = None):
        self.schema_service = schema_service or SchemaService()
        self.pruner = SchemaPruner()


    def build_grounded_schema(
        self,
        schema: Optional[Dict[str, Any]] = None,
        query_understanding: Optional[QueryUnderstanding] = None,
        question: Optional[str] = None,
        analysis_type: Optional[AnalysisType] = None,
        catalog: Optional[SchemaCatalog] = None,
    ) -> GroundedSchema:
        """Sync version of build_grounded_schema. Uses sync retrieve_relevant_tables."""
        return self._build_grounded_schema_internal(
            schema, query_understanding, question, analysis_type, catalog, is_async=False
        )

    async def build_grounded_schema_async(
        self,
        schema: Optional[Dict[str, Any]] = None,
        query_understanding: Optional[QueryUnderstanding] = None,
        question: Optional[str] = None,
        analysis_type: Optional[AnalysisType] = None,
        catalog: Optional[SchemaCatalog] = None,
    ) -> GroundedSchema:
        """Async version of build_grounded_schema for use in running event loops."""
        # For large schemas requiring async retrieval:
        _MAX_SEED_TABLES = getattr(settings, "grounding_max_seed_tables", 5)
        async_retrieved = None
        db_ctx = None
        if hasattr(self, "schema_service") and self.schema_service:
            try:
                candidate_ctx = self.schema_service.get_database_context()
                if candidate_ctx and hasattr(candidate_ctx, "schema") and isinstance(candidate_ctx.schema, dict):
                    if schema is None or schema is candidate_ctx.schema or compute_structural_schema_fingerprint(schema) == getattr(candidate_ctx, "fingerprint", None):
                        db_ctx = candidate_ctx
            except Exception:
                db_ctx = None
        cat = catalog or (db_ctx.catalog if db_ctx else None)
        if question and cat is not None and schema and len(schema) > settings.large_schema_table_threshold:
            cached_retriever = db_ctx.tfidf_retriever if db_ctx else None
            cached_emb_retriever = db_ctx.embedding_retriever if db_ctx else None
            from app.models.schema_catalog.retrieval import HybridCandidateRetriever
            async_retrieved = await HybridCandidateRetriever(
                catalog=cat,
                tfidf_retriever=cached_retriever,
                embedding_retriever=cached_emb_retriever,
            ).retrieve_candidate_tables_async(question, k=_MAX_SEED_TABLES)

        return self._build_grounded_schema_internal(
            schema, query_understanding, question, analysis_type, cat, is_async=True, pre_retrieved=async_retrieved
        )

    def _build_grounded_schema_internal(
        self,
        schema: Optional[Dict[str, Any]] = None,
        query_understanding: Optional[QueryUnderstanding] = None,
        question: Optional[str] = None,
        analysis_type: Optional[AnalysisType] = None,
        catalog: Optional[SchemaCatalog] = None,
        is_async: bool = False,
        pre_retrieved: Optional[list] = None,
    ) -> GroundedSchema:
        """
        Build a compact GroundedSchema object containing only relevant tables and join paths.
        """
        import time
        t_grounding_start = time.perf_counter()

        db_ctx = None
        if hasattr(self, "schema_service") and self.schema_service:
            try:
                candidate_ctx = self.schema_service.get_database_context()
                if candidate_ctx and hasattr(candidate_ctx, "schema") and isinstance(candidate_ctx.schema, dict):
                    db_ctx = candidate_ctx
            except Exception:
                db_ctx = None

        if schema is None and db_ctx is not None:
            schema = db_ctx.schema
            fingerprint = db_ctx.fingerprint
            catalog = catalog or db_ctx.catalog
        elif db_ctx is not None and schema is not None:
            fingerprint = compute_structural_schema_fingerprint(schema)
            if fingerprint != getattr(db_ctx, "fingerprint", None):
                db_ctx = None
            else:
                catalog = catalog or db_ctx.catalog
        else:
            fingerprint = compute_structural_schema_fingerprint(schema) if schema else ""

        if not schema:
            return GroundedSchema()

        # If DatabaseContext has pre-built join graph and retrievers, use them instantly (0ms)
        cached_emb_retriever = None
        if db_ctx and getattr(db_ctx, "relationship_graph", None) and getattr(db_ctx, "tfidf_retriever", None):
            graph = db_ctx.relationship_graph
            cached_retriever = db_ctx.tfidf_retriever
            cached_emb_retriever = db_ctx.embedding_retriever
            intel_hit = True
            intel_lookup_ms = 0.0
            intel_build_ms = 0.0
        else:
            bundle, intel_hit, intel_lookup_ms, intel_build_ms = SchemaIntelligenceCache.get_or_build(
                fingerprint, schema, catalog=catalog
            )
            graph = bundle.relationship_graph
            cached_retriever = bundle.tfidf_retriever
            cached_emb_retriever = getattr(bundle, "embedding_retriever", None)

        # Extract target seed tables
        t_tab_start = time.perf_counter()

        seed_tables: Set[str] = set()

        if query_understanding:
            # 1. Direct entities
            for entity in query_understanding.entities:
                if entity in schema:
                    seed_tables.add(entity)
                elif f"public.{entity}" in schema:
                    seed_tables.add(f"public.{entity}")
                elif entity.split(".")[-1] in schema:
                    seed_tables.add(entity.split(".")[-1])
                elif db_ctx and db_ctx.keyword_to_tables:
                    matched = db_ctx.match_seed_tables_fast(entity, max_tables=3)
                    seed_tables.update(matched)

            # 2. Table references inside metrics & dimensions (e.g. "Invoice.Total")
            for ref in query_understanding.metrics + query_understanding.dimensions:
                if "." in ref:
                    t_name = ref.split(".")[0]
                    if t_name in schema:
                        seed_tables.add(t_name)

        is_large_schema = len(schema) > settings.large_schema_table_threshold
        # Maximum seed tables (3-5) and final tables (adaptive up to 15) to send to LLM
        _MAX_SEED_TABLES = getattr(settings, "grounding_max_seed_tables", 5)
        _MAX_FINAL_TABLES = getattr(settings, "grounding_max_final_tables", 15)

        table_retrieval_ms = 0.0
        column_retrieval_ms = 0.0
        fallback_triggered = False
        table_candidates = []
        column_candidates = []

        # --- Stage 1: Table Candidate Retrieval (Multi-Signal: Lexical + Vector ANN + Alias) ---
        if question:
            q_lower = expand_with_arabic_terms(question.lower())

            # 1. Fast 0ms Inverted Keyword Index lookup from RAM (Literal/Exact Table Anchors first)
            t_literal_tab_start = time.perf_counter()
            if db_ctx and db_ctx.keyword_to_tables:
                fast_matches = db_ctx.match_seed_tables_fast(q_lower, max_tables=_MAX_SEED_TABLES)
                seed_tables.update(fast_matches)
            table_retrieval_ms += (time.perf_counter() - t_literal_tab_start) * 1000

            # 2. Multi-signal Hybrid Candidate Retriever (Lexical + Vector + Alias)
            if catalog is not None and len(seed_tables) < _MAX_SEED_TABLES:
                t_cand_start = time.perf_counter()
                if pre_retrieved is not None:
                    table_candidates = [c for c in pre_retrieved if hasattr(c, "table_name")]
                    retrieved_tables = [
                        c.table_name if hasattr(c, "table_name") else c
                        for c in pre_retrieved
                    ]
                else:
                    from app.models.schema_catalog.retrieval import HybridCandidateRetriever
                    cand_retriever = (
                        db_ctx.candidate_retriever
                        if db_ctx and getattr(db_ctx, "candidate_retriever", None)
                        else HybridCandidateRetriever(
                            catalog=catalog,
                            tfidf_retriever=cached_retriever,
                            embedding_retriever=cached_emb_retriever,
                        )
                    )
                    cands = cand_retriever.retrieve_candidate_tables(question, k=_MAX_SEED_TABLES)
                    table_candidates = cands
                    retrieved_tables = [c.table_name for c in cands]

                table_retrieval_ms += (time.perf_counter() - t_cand_start) * 1000
                if retrieved_tables:
                    for t in retrieved_tables:
                        if t in schema and len(seed_tables) < _MAX_SEED_TABLES:
                            seed_tables.add(t)

        # --- Stage 2: Column Candidate Retrieval within Candidate Tables ---
        if seed_tables and catalog is not None:
            t_col_start = time.perf_counter()
            try:
                from app.models.schema_catalog.retrieval import HybridCandidateRetriever
                cand_retriever = (
                    db_ctx.candidate_retriever
                    if db_ctx and getattr(db_ctx, "candidate_retriever", None)
                    else HybridCandidateRetriever(catalog=catalog)
                )
                col_cands = cand_retriever.retrieve_candidate_columns(question or "", list(seed_tables))
                column_candidates = col_cands
                # Add any table with a very strong column match
                for col_c in col_cands:
                    if col_c.score >= 1.5 and col_c.table_name in schema and len(seed_tables) < _MAX_SEED_TABLES:
                        seed_tables.add(col_c.table_name)
            except Exception as e:
                logger.debug("Column candidate retrieval error: %s", e)
            column_retrieval_ms += (time.perf_counter() - t_col_start) * 1000

        # If no seeds identified, select bounded subset (3-5 tables max, never full database)
        if not seed_tables:
            if len(schema) <= 6:
                seed_tables = set(schema.keys())
            else:
                if question and catalog is not None:
                    t_tab_start = time.perf_counter()
                    if pre_retrieved is not None:
                        retrieved = [
                            c.table_name if hasattr(c, "table_name") else c
                            for c in pre_retrieved
                        ]
                    else:
                        from app.models.schema_catalog.retrieval import HybridCandidateRetriever
                        table_candidates = HybridCandidateRetriever(
                            catalog=catalog,
                            tfidf_retriever=cached_retriever,
                            embedding_retriever=cached_emb_retriever,
                        ).retrieve_candidate_tables(
                            question, k=_MAX_SEED_TABLES
                        )
                        retrieved = [c.table_name for c in table_candidates]
                    table_retrieval_ms += (time.perf_counter() - t_tab_start) * 1000
                    if retrieved:
                        seed_tables = {t for t in retrieved if t in schema}
                if not seed_tables:
                    # Fall back to top FK-centrality ranking (capped to 4-5 tables)
                    seed_tables = set(graph.get_most_central_tables(limit=_MAX_SEED_TABLES))
                    fallback_triggered = True

        # --- Stage 3: Join Neighbor Expansion via Foreign-Key Graph ---
        if analysis_type in _NEEDS_NEIGHBOR_EXPANSION:
            widened = set(seed_tables)
            for t in seed_tables:
                for neighbor in graph.get_direct_neighbors(t):
                    if neighbor in seed_tables or _has_metric_column(schema.get(neighbor, {})):
                        widened.add(neighbor)
            seed_tables = widened

        # Cap seed tables to 3-5 tables
        if len(seed_tables) > _MAX_SEED_TABLES:
            entity_set = set()
            if query_understanding:
                entity_set = set(query_understanding.entities)
            prioritized = sorted(
                seed_tables,
                key=lambda t: (t in entity_set, len(graph.adj_list.get(t, []))),
                reverse=True,
            )
            seed_tables = set(prioritized[:_MAX_SEED_TABLES])

        logger.debug(
            "Schema grounding: %d seed tables selected from %d total",
            len(seed_tables), len(schema),
        )

        # Expand seed tables through adaptive foreign-key join paths (preserving bridge connectivity)
        t_rel_start = time.perf_counter()
        minimal_tables = graph.get_adaptive_connecting_tables(
            seed_tables,
            max_budget=_MAX_FINAL_TABLES,
            preserve_bridges=True,
        )
        relationship_expansion_ms = (time.perf_counter() - t_rel_start) * 1000

        # Prune and format compact schema text with explicit join paths and column pruning
        t_prune_start = time.perf_counter()
        grounded = self.pruner.prune_and_format(
            schema,
            minimal_tables,
            graph.relationships,
            seed_tables=seed_tables,
            query_understanding=query_understanding,
        )

        schema_pruning_ms = (time.perf_counter() - t_prune_start) * 1000

        grounding_ms = (time.perf_counter() - t_grounding_start) * 1000

        grounded.retrieved_seed_tables = sorted(list(seed_tables))
        grounded.timings_ms = {
            "table_retrieval_ms": table_retrieval_ms,
            "column_retrieval_ms": column_retrieval_ms,
            "relationship_expansion_ms": relationship_expansion_ms,
            "schema_pruning_ms": schema_pruning_ms,
            "schema_grounding_ms": grounding_ms,
            "schema_intelligence_cache_lookup_ms": round(intel_lookup_ms, 2),
            "schema_intelligence_build_ms": round(intel_build_ms, 2),
            "schema_intelligence_cache_hit": intel_hit,
        }
        if fallback_triggered:
            grounded.fallback_used = True

        explicit_entities = set(query_understanding.entities) if query_understanding else set()
        has_entity_match = bool(explicit_entities & set(grounded.selected_tables))
        has_glossary_match = any("alias" in c.match_sources for c in table_candidates)
        has_embedding_rel = any("vector_ann" in c.match_sources for c in table_candidates)
        has_col_match = any(bool(c.match_sources) for c in column_candidates)

        grounded.evidence = {
            "exact_entity_match": has_entity_match,
            "glossary_match": has_glossary_match,
            "embedding_relevance": has_embedding_rel,
            "column_relevance": has_col_match,
            # A relationship is evidence only when the selected seed tables
            # actually require a join; a central table alone earns no credit.
            "join_path_confidence": len(seed_tables) > 1 and bool(grounded.required_relationships),
            "retrieval_sources": sorted({source for c in table_candidates for source in c.match_sources}),
        }

        # If fallback was used and the question asks for concepts completely absent from schema
        if fallback_triggered and question:
            # Check if query understanding extracted explicit entities that are completely missing
            known_tables = set(schema.keys())
            known_short = {t.split(".")[-1].lower() for t in known_tables}
            
            all_schema_terms = set(known_short)
            for t, info in schema.items():
                all_schema_terms.add(t.lower())
                cols = info.get("columns", []) if isinstance(info, dict) else []
                for c in cols:
                    c_name = c.get("name", "") if isinstance(c, dict) else str(c)
                    all_schema_terms.add(c_name.lower())

            q_tokens = [w for w in re.findall(r"\b[a-zA-Z\u0621-\u064A]{3,}\b", question.lower()) if w not in _STOPWORDS]
            has_token_overlap = any(any(tok in term or term in tok for term in all_schema_terms) for tok in q_tokens)
            has_strong_candidate = any(getattr(c, "score", 0) >= 0.5 for c in table_candidates) or any(getattr(c, "score", 0) >= 0.8 for c in column_candidates)

            if not has_token_overlap and not has_strong_candidate and len(q_tokens) >= 2:
                grounded.is_grounded = False
                grounded.unsupported = True
                grounded.unsupported_reason = (
                    f"No database tables or columns in the schema relate to the request: '{question}'."
                )
                logger.info("Schema Grounding: Flagged question as unsupported due to lack of grounded evidence: %s", question)

        return grounded


