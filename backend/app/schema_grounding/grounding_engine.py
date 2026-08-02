"""Schema Grounding Engine — discovers minimal required schema subsets and join paths."""
from typing import Any, Dict, Optional, Set
from app.services.sql_service import SchemaService
from app.semantic.models import QueryUnderstanding
from app.schema_grounding.models import GroundedSchema
from app.schema_grounding.relationship_graph import SchemaRelationshipGraph
from app.schema_grounding.schema_pruner import SchemaPruner
from app.utils.text_processor import AnalysisType, COMPLEX_ANALYSIS_TYPES
from app.schema_grounding.arabic_terms import expand_with_arabic_terms
from app.schema_catalog.models import SchemaCatalog
from app.schema_catalog.retrieval import retrieve_relevant_tables
from app.core.config import settings

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
        """
        Build a compact GroundedSchema object containing only relevant tables and join paths.

        Args:
            schema: Optional full database schema dict. If None, fetched via SchemaService.
            query_understanding: Optional QueryUnderstanding object containing entities and metrics.
            question: Optional user question string to match against tables/columns.
            analysis_type: Optional classification (see app.utils.text_processor). When the
                type is COMPARISON/TREND/ROOT_CAUSE/MULTI_STEP/RANKING, seed tables are
                widened by one FK hop — these question types routinely name only one side
                of the join the SQL actually needs (e.g. "compare employees" needs the
                linked Orders table to compute anything comparable).
            catalog: Optional Schema Catalog (Phase 1). When the schema is large
                (> settings.large_schema_table_threshold tables) and the catalog has a
                built glossary (Phase 1/2), Phase 3's TF-IDF retrieval replaces the blind
                FK-centrality fallback for questions that matched no literal seed table.

        Returns:
            GroundedSchema: Minimal grounded schema object with compact schema_text.
        """
        if schema is None:
            schema = self.schema_service.get_schema()

        if not schema:
            return GroundedSchema()

        graph = SchemaRelationshipGraph(schema)

        # Extract target seed tables
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

        if question:
            # Zero-cost: append English equivalents for common Arabic business
            # nouns (عميل->customer, طلب->order, ...) BEFORE literal matching,
            # so Arabic questions match English table/column names without
            # needing the (LLM-built) glossary to exist yet.
            q_lower = expand_with_arabic_terms(question.lower())
            for table_name, info in schema.items():
                t_lower = table_name.lower()
                # Match table name or singular/plural forms
                if (
                    t_lower in q_lower
                    or (t_lower + "s") in q_lower
                    or (t_lower + "es") in q_lower
                    or (t_lower.endswith("y") and t_lower[:-1] + "ies" in q_lower)
                    or (q_lower.endswith("s") and q_lower[:-1] == t_lower)
                    # Reverse direction: many schemas name tables in the
                    # plural already (Categories, Products); a question
                    # phrased in the singular ("per category") wouldn't
                    # match t_lower directly without this.
                    or (t_lower.endswith("ies") and (t_lower[:-3] + "y") in q_lower)
                    or (t_lower.endswith("es") and t_lower[:-2] in q_lower and len(t_lower) > 4)
                    or (t_lower.endswith("s") and not t_lower.endswith("ss") and t_lower[:-1] in q_lower and len(t_lower) > 4)
                ):
                    seed_tables.add(table_name)
                else:
                    # Match column names
                    matched = False
                    for col in info.get("columns", []):
                        col_lower = col["name"].lower()
                        if len(col_lower) > 3 and col_lower in q_lower:
                            seed_tables.add(table_name)
                            matched = True
                            break
                    # Match column SAMPLE VALUES (e.g. question says "Canada",
                    # the column is named "Country" but the sample values —
                    # already captured by SchemaService — include "Canada").
                    # Without this, value-based questions ("compare sales in
                    # the USA vs Canada") only ground whichever table happens
                    # to have a coincidentally-matching column name (e.g.
                    # "Total"), and silently miss the table the filter
                    # actually applies to.
                    if not matched:
                        for col in info.get("columns", []):
                            for sample in col.get("samples", []) or []:
                                sample_lower = str(sample).strip().lower()
                                if len(sample_lower) > 2 and sample_lower in q_lower:
                                    seed_tables.add(table_name)
                                    matched = True
                                    break
                            if matched:
                                break

        # If no seeds identified, keep all tables as fallback
        if not seed_tables:
            if len(schema) > settings.large_schema_table_threshold:
                if question and catalog is not None:
                    retrieved = retrieve_relevant_tables(question, catalog, k=settings.retrieval_top_k_tables)
                    if retrieved:
                        seed_tables = {t for t in retrieved if t in schema}
                if not seed_tables:
                    # No catalog/glossary yet, or TF-IDF found no vocabulary
                    # overlap at all — fall back to blind FK-centrality
                    # ranking rather than returning nothing.
                    seed_tables = graph.get_most_central_tables(limit=15)
            else:
                seed_tables = set(schema.keys())
        elif analysis_type in _NEEDS_NEIGHBOR_EXPANSION:
            # Widen by one FK hop for question types that typically need a
            # linked table the question text didn't literally name — but
            # only pull in neighbors that actually carry a metric (a numeric,
            # non-key column). Pulling every FK-connected table indiscriminately
            # (junction/lookup tables like EmployeeTerritories, CustomerDemo)
            # widens recall but also reintroduces the token bloat this whole
            # grounding step exists to avoid, for zero benefit — those tables
            # have nothing to aggregate or compare.
            widened = set(seed_tables)
            for t in seed_tables:
                for neighbor in graph.get_direct_neighbors(t):
                    if neighbor in seed_tables or _has_metric_column(schema.get(neighbor, {})):
                        widened.add(neighbor)
            seed_tables = widened

        # Expand seed tables through shortest foreign-key join paths
        minimal_tables = graph.get_minimal_connecting_tables(seed_tables)

        # Prune and format compact schema text
        return self.pruner.prune_and_format(schema, minimal_tables, graph.relationships)
