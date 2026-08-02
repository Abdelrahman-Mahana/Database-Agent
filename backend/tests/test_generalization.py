"""Phase 4 (rebuild plan): generalization smoke tests.

The rest of the test suite exercises grounding/retrieval against
Chinook/Northwind-style schemas with clear, English, business-meaningful
table names (Artist, Invoice, Customer...). Phase 4 of the rebuild plan
specifically calls out the risk that real-world databases often look
nothing like that (`tbl_x1`, `col_a`, opaque legacy naming) and asks to
verify the FK-centrality fallback still behaves sanely there.

These tests build a synthetic schema with deliberately meaningless names
and check the DETERMINISTIC parts of the pipeline only (relationship graph,
FK-centrality ranking, large-schema fallback threshold) — no LLM/embedding
calls, so they run offline in CI with zero cost, same as
test_schema_grounding.py.
"""
import pytest

from app.schema_grounding.relationship_graph import SchemaRelationshipGraph
from app.schema_grounding.grounding_engine import SchemaGroundingEngine
from app.semantic.models import QueryUnderstanding, OutputFormat
from app.utils.text_processor import AnalysisType


def _obscure_table(n_cols: int = 2, fk: dict | None = None) -> dict:
    cols = [{"name": f"col_{i}", "type": "INTEGER" if i == 0 else "VARCHAR"} for i in range(n_cols)]
    return {
        "columns": cols,
        "primary_key": [cols[0]["name"]],
        "foreign_keys": [fk] if fk else [],
    }


@pytest.fixture
def obscure_schema() -> dict:
    """40 tables named tbl_x0..tbl_x39 in a simple hub-and-spoke FK graph
    around tbl_x0 (the most 'central' table), with meaningless column names
    throughout - nothing here would match on literal keyword/substring
    search against any real question."""
    schema: dict = {"tbl_x0": _obscure_table(3)}
    for i in range(1, 40):
        schema[f"tbl_x{i}"] = _obscure_table(
            2, fk={"constrained_columns": ["col_0"], "referred_table": "tbl_x0", "referred_columns": ["col_0"]}
        )
    return schema


def test_relationship_graph_builds_on_obscure_names(obscure_schema):
    """FK edges resolve correctly regardless of naming - the graph only
    cares about the foreign_keys structure, never the names themselves."""
    graph = SchemaRelationshipGraph(obscure_schema)
    neighbors = graph.get_direct_neighbors("tbl_x0")
    assert len(neighbors) == 39, "tbl_x0 should be FK-connected to all 39 spoke tables"


def test_fk_centrality_ranks_the_hub_table_first(obscure_schema):
    """The FK-centrality fallback (used when literal/TF-IDF/embedding
    retrieval all found nothing) should surface tbl_x0 first - it's the
    most-connected table - even though its name carries zero semantic
    signal. This is the safety net Phase 4 asks to verify."""
    graph = SchemaRelationshipGraph(obscure_schema)
    central = graph.get_most_central_tables(limit=5)
    assert central, "FK-centrality fallback must never return empty on a connected schema"
    assert central[0] == "tbl_x0"


def test_grounding_falls_back_to_fk_centrality_when_large_and_unmatched(obscure_schema):
    """A question that shares no vocabulary with any table/column name, on
    a schema above the large-schema threshold and with no catalog/glossary
    available yet, must still ground to *something* useful (the FK-central
    tables) rather than an empty/all-tables schema."""
    engine = SchemaGroundingEngine()
    qu = QueryUnderstanding(
        raw_question="what is the meaning of life",
        analysis_type=AnalysisType.UNKNOWN,
        entities=[], metrics=[], dimensions=[], filters=[], time_expressions=[],
        aggregations=[], sorting=[], limit=None, expected_output=OutputFormat.TABLE,
    )
    grounded = engine.build_grounded_schema(
        schema=obscure_schema, query_understanding=qu,
        question="what is the meaning of life", analysis_type=AnalysisType.UNKNOWN, catalog=None,
    )
    assert grounded.selected_tables, "must not ground to an empty schema on a large, unmatched question"
    assert "tbl_x0" in grounded.selected_tables, "FK-centrality fallback should have pulled in the hub table"
    # And it must not have silently fallen back to "just include every table"
    assert len(grounded.selected_tables) < len(obscure_schema)


def test_grounding_still_grounds_small_obscure_schema_fully(obscure_schema):
    """Below the large-schema threshold, an unmatched question should keep
    the existing 'small schema -> include everything' behavior (cheap and
    safe at that size) rather than switching retrieval strategies."""
    small_schema = {k: obscure_schema[k] for k in list(obscure_schema)[:5]}
    engine = SchemaGroundingEngine()
    qu = QueryUnderstanding(
        raw_question="irrelevant question",
        analysis_type=AnalysisType.UNKNOWN,
        entities=[], metrics=[], dimensions=[], filters=[], time_expressions=[],
        aggregations=[], sorting=[], limit=None, expected_output=OutputFormat.TABLE,
    )
    grounded = engine.build_grounded_schema(
        schema=small_schema, query_understanding=qu,
        question="irrelevant question", analysis_type=AnalysisType.UNKNOWN, catalog=None,
    )
    assert set(grounded.selected_tables) == set(small_schema.keys())
