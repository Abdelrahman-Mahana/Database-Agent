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
            async_retrieved = await retrieve_relevant_tables_async(
                question, catalog, k=_MAX_SEED_TABLES,
                cached_retriever=cached_retriever,
                cached_embedding_retriever=cached_emb_retriever,
            )

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
        # Maximum seed tables (3-5) and final tables (3-8) to send to LLM
        _MAX_SEED_TABLES = getattr(settings, "grounding_max_seed_tables", 5)
        _MAX_FINAL_TABLES = getattr(settings, "grounding_max_final_tables", 8)

        table_retrieval_ms = 0.0
        column_retrieval_ms = 0.0
        fallback_triggered = False

        if question:
            q_lower = expand_with_arabic_terms(question.lower())

            # For large schemas, try pre-indexed TF-IDF / embedding retrieval FIRST
            if is_large_schema and catalog is not None:
                t_tfidf_start = time.perf_counter()
                if pre_retrieved is not None:
                    retrieved = pre_retrieved
                else:
                    retrieved = retrieve_relevant_tables(
                        question, catalog, k=_MAX_SEED_TABLES,
                        cached_retriever=cached_retriever,
                        cached_embedding_retriever=cached_emb_retriever,
                    )
                table_retrieval_ms += (time.perf_counter() - t_tfidf_start) * 1000
                if retrieved:
                    seed_tables.update(t for t in retrieved if t in schema)

            # Fast 0ms inverted keyword index lookup from RAM (replaces linear table/column scan)
            t_literal_tab_start = time.perf_counter()
            if db_ctx and db_ctx.keyword_to_tables and len(seed_tables) < _MAX_SEED_TABLES:
                fast_matches = db_ctx.match_seed_tables_fast(q_lower, max_tables=_MAX_SEED_TABLES)
                seed_tables.update(fast_matches)
                table_retrieval_ms += (time.perf_counter() - t_literal_tab_start) * 1000
            else:
                # Fallback to linear scan only if db_ctx not available
                for table_name in schema.keys():
                    if len(seed_tables) >= _MAX_SEED_TABLES:
                        break
                    t_lower = table_name.lower()
                    if (
                        t_lower in q_lower
                        or (t_lower + "s") in q_lower
                        or (t_lower + "es") in q_lower
                        or (t_lower.endswith("y") and t_lower[:-1] + "ies" in q_lower)
                        or (q_lower.endswith("s") and q_lower[:-1] == t_lower)
                        or (t_lower.endswith("ies") and (t_lower[:-3] + "y") in q_lower)
                        or (t_lower.endswith("es") and t_lower[:-2] in q_lower and len(t_lower) > 4)
                        or (t_lower.endswith("s") and not t_lower.endswith("ss") and t_lower[:-1] in q_lower and len(t_lower) > 4)
                    ):
                        seed_tables.add(table_name)
                table_retrieval_ms += (time.perf_counter() - t_literal_tab_start) * 1000

                t_col_start = time.perf_counter()
                for table_name, info in schema.items():
                    if len(seed_tables) >= _MAX_SEED_TABLES:
                        break
                    min_col_len = 6 if is_large_schema else 4
                    matched = False
                    for col in info.get("columns", []):
                        col_lower = col["name"].lower()
                        if len(col_lower) >= min_col_len and col_lower in q_lower:
                            seed_tables.add(table_name)
                            matched = True
                            break
                column_retrieval_ms = (time.perf_counter() - t_col_start) * 1000

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
                        retrieved = pre_retrieved
                    else:
                        retrieved = retrieve_relevant_tables(
                            question, catalog, k=_MAX_SEED_TABLES, cached_retriever=cached_retriever
                        )
                    table_retrieval_ms += (time.perf_counter() - t_tab_start) * 1000
                    if retrieved:
                        seed_tables = {t for t in retrieved if t in schema}
                if not seed_tables:
                    # Fall back to top FK-centrality ranking (capped to 4-5 tables)
                    seed_tables = set(graph.get_most_central_tables(limit=_MAX_SEED_TABLES))
                    fallback_triggered = True
        elif analysis_type in _NEEDS_NEIGHBOR_EXPANSION:
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

        # Expand seed tables through shortest foreign-key join paths
        t_rel_start = time.perf_counter()
        minimal_tables = graph.get_minimal_connecting_tables(seed_tables)

        # Enforce strict 3-8 table cap on minimal_tables while preserving bridge tables
        if len(minimal_tables) > _MAX_FINAL_TABLES:
            # Active degree inside minimal_tables
            m_degree = {t: sum(1 for n, _, _ in graph.adj_list.get(t, []) if n in minimal_tables) for t in minimal_tables}
            ranked = sorted(
                minimal_tables,
                key=lambda t: (
                    t in seed_tables,         # 1. Keep requested seed tables
                    m_degree.get(t, 0) >= 2,  # 2. Keep bridge / junction tables connecting the paths
                    m_degree.get(t, 0),       # 3. Keep higher degree hubs
                ),
                reverse=True,
            )
            minimal_tables = set(ranked[:_MAX_FINAL_TABLES])

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

        return grounded
