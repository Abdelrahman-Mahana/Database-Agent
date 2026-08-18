"""Schema Grounding Engine — discovers minimal required schema subsets and join paths."""
from typing import Any, Dict, Optional, Set

from loguru import logger

from app.services.sql_service import SchemaService
from app.semantic.models import QueryUnderstanding
from app.schema_grounding.models import GroundedSchema
from app.schema_grounding.schema_intelligence import (
    SchemaIntelligenceCache,
    compute_structural_schema_fingerprint,
)
from app.schema_grounding.relationship_graph import SchemaRelationshipGraph
from app.schema_grounding.schema_pruner import SchemaPruner
from app.utils.text_processor import AnalysisType, COMPLEX_ANALYSIS_TYPES
from app.schema_grounding.arabic_terms import expand_with_arabic_terms
from app.schema_catalog.models import SchemaCatalog
from app.schema_catalog.retrieval import retrieve_relevant_tables, retrieve_relevant_tables_async
from app.config.settings import settings

# COMPARISON/RANKING questions frequently name only one side of a metric
# ("compare employees", "top artists") while the actual metric lives in a
# linked table (Orders/Invoice). Widening by one FK hop for these types
# catches that without ballooning the grounded schema for simple questions.
_NEEDS_NEIGHBOR_EXPANSION = COMPLEX_ANALYSIS_TYPES | {AnalysisType.RANKING}

_NUMERIC_TYPE_MARKERS = ("INT", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL", "REAL", "MONEY")
_ID_NAME_MARKERS = ("id", "_id", "code", "key")


def _has_metric_column(table_info: Dict[str, Any]) -> bool:
    """True if a table has at least one numeric column that isn't just an ID/FK
    (i.e. something worth aggregating/comparing — Freight, Total, UnitPrice —
    as opposed to a junction table that's purely IDs)."""
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
        if question and catalog is not None and schema and len(schema) > settings.large_schema_table_threshold:
            db_ctx = self.schema_service.get_database_context() if schema is None else None
            cached_retriever = db_ctx.tfidf_retriever if db_ctx else None
            cached_emb_retriever = db_ctx.embedding_retriever if db_ctx else None
            from app.schema_catalog.retrieval import HybridCandidateRetriever
            async_retrieved = await HybridCandidateRetriever(
                catalog=catalog,
                tfidf_retriever=cached_retriever,
                embedding_retriever=cached_emb_retriever,
            ).retrieve_candidate_tables_async(question, k=_MAX_SEED_TABLES)

        return self._build_grounded_schema_internal(
            schema, query_understanding, question, analysis_type, catalog, is_async=True, pre_retrieved=async_retrieved
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
        if schema is None:
            db_ctx = self.schema_service.get_database_context()
            schema = db_ctx.schema
            fingerprint = db_ctx.fingerprint
            catalog = catalog or db_ctx.catalog
        else:
            fingerprint = compute_structural_schema_fingerprint(schema)

        if not schema:
            return GroundedSchema()

        # If DatabaseContext has pre-built join graph and retrievers, use them instantly (0ms)
        cached_emb_retriever = None
        if db_ctx and db_ctx.relationship_graph:
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

            # 1. Multi-signal Hybrid Candidate Retriever (Lexical + Vector + Alias)
            if catalog is not None:
                t_cand_start = time.perf_counter()
                if pre_retrieved is not None:
                    table_candidates = [c for c in pre_retrieved if hasattr(c, "table_name")]
                    retrieved_tables = [
                        c.table_name if hasattr(c, "table_name") else c
                        for c in pre_retrieved
                    ]
                else:
                    from app.schema_catalog.retrieval import HybridCandidateRetriever
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
                    seed_tables.update(t for t in retrieved_tables if t in schema)

            # 2. Fast 0ms Inverted Keyword Index lookup from RAM
            t_literal_tab_start = time.perf_counter()
            if db_ctx and db_ctx.keyword_to_tables and len(seed_tables) < _MAX_SEED_TABLES:
                fast_matches = db_ctx.match_seed_tables_fast(q_lower, max_tables=_MAX_SEED_TABLES)
                seed_tables.update(fast_matches)
            table_retrieval_ms += (time.perf_counter() - t_literal_tab_start) * 1000

        # --- Stage 2: Column Candidate Retrieval within Candidate Tables ---
        if seed_tables and catalog is not None:
            t_col_start = time.perf_counter()
            try:
                from app.schema_catalog.retrieval import HybridCandidateRetriever
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

        # Complete initial table retrieval timing
        table_retrieval_ms += (time.perf_counter() - t_tab_start) * 1000 - table_retrieval_ms - column_retrieval_ms

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
                        from app.schema_catalog.retrieval import HybridCandidateRetriever
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
        grounded.evidence = {
            "exact_entity_match": bool(explicit_entities & set(grounded.selected_tables)),
            "glossary_match": any("alias" in c.match_sources for c in table_candidates),
            "embedding_relevance": any("vector_ann" in c.match_sources for c in table_candidates),
            "column_relevance": any(bool(c.match_sources) for c in column_candidates),
            # A relationship is evidence only when the selected seed tables
            # actually require a join; a central table alone earns no credit.
            "join_path_confidence": len(seed_tables) > 1 and bool(grounded.required_relationships),
            "retrieval_sources": sorted({source for c in table_candidates for source in c.match_sources}),
        }

        return grounded
