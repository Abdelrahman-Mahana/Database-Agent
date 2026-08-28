"""Tests verifying that the Schema Grounding Gate prevents LLM hallucinations of entities, metrics, and columns."""
import pytest
from app.models.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile
from app.agent.semantic.grounding_gate import schema_grounding_gate, SchemaGroundingGate
from app.agent.semantic.models import QuerySpec, AnalysisType, OutputFormat, IntentType, ExecutionRoute
from app.agent.semantic.query_spec_builder import QuerySpecBuilder
from app.agent.semantic.contract_builder import semantic_contract_builder


_MOCK_SCHEMA = {
    "customers": {
        "columns": [
            {"name": "id", "type": "INTEGER"},
            {"name": "name", "type": "VARCHAR"},
            {"name": "country", "type": "VARCHAR"},
        ]
    },
    "orders": {
        "columns": [
            {"name": "id", "type": "INTEGER"},
            {"name": "customer_id", "type": "INTEGER"},
            {"name": "amount", "type": "NUMERIC"},
            {"name": "order_date", "type": "DATE"},
        ]
    }
}

_MOCK_CATALOG = SchemaCatalog(
    fingerprint="mock_fp",
    dialect="sqlite",
    database_name="TestDB",
    tables={
        "customers": TableProfile(
            name="customers",
            columns=[
                ColumnProfile(name="id", type="INTEGER", primary_key=True),
                ColumnProfile(name="name", type="VARCHAR"),
                ColumnProfile(name="country", type="VARCHAR"),
            ]
        ),
        "orders": TableProfile(
            name="orders",
            columns=[
                ColumnProfile(name="id", type="INTEGER", primary_key=True),
                ColumnProfile(name="customer_id", type="INTEGER"),
                ColumnProfile(name="amount", type="NUMERIC"),
                ColumnProfile(name="order_date", type="DATE"),
            ]
        )
    }
)


def test_grounding_gate_rejects_hallucinated_entities():
    """Gate must reject table names that do not exist in schema or catalog."""
    raw_entities = ["fake_sales_table", "orders", "random_entity", "customer"]
    grounded = schema_grounding_gate.filter_grounded_entities(
        raw_entities,
        schema=_MOCK_SCHEMA,
        catalog=_MOCK_CATALOG,
    )

    assert "orders" in grounded
    assert "customers" in grounded  # Resolved singular "customer" to canonical "customers"
    assert "fake_sales_table" not in grounded
    assert "random_entity" not in grounded


def test_grounding_gate_rejects_hallucinated_dimensions():
    """Gate must reject column/dimension names that do not exist in candidate tables or schema."""
    raw_dims = ["country", "customers.name", "orders.fake_column", "hallucinated_metric_col"]
    grounded = schema_grounding_gate.filter_grounded_dimensions(
        raw_dims,
        candidate_tables=["customers", "orders"],
        schema=_MOCK_SCHEMA,
        catalog=_MOCK_CATALOG,
    )

    assert "country" in grounded
    assert "customers.name" in grounded
    assert "orders.fake_column" not in grounded
    assert "hallucinated_metric_col" not in grounded


def test_merge_llm_and_deterministic_filters_hallucinations():
    """When merging LLM understanding, ungrounded tables and columns must be filtered out."""
    builder = QuerySpecBuilder()

    llm_spec = QuerySpec(
        raw_question="Top customers by revenue",
        entities=["nonexistent_table", "customers"],
        dimensions=["country", "hallucinated_age_group"],
        metrics=["revenue"],
        analysis_type=AnalysisType.RANKING,
        limit=5,
    )

    deterministic_spec = QuerySpec(
        raw_question="Top customers by revenue",
        entities=["customers"],
        dimensions=["country"],
        metrics=[],
        aggregations=["SUM"],
        analysis_type=AnalysisType.RANKING,
        limit=5,
    )

    merged = builder._merge_llm_and_deterministic_specs(
        llm_spec=llm_spec,
        deterministic_spec=deterministic_spec,
        schema=_MOCK_SCHEMA,
        catalog=_MOCK_CATALOG,
    )

    # Only grounded entities and dimensions should remain
    assert "nonexistent_table" not in merged.entities
    assert "customers" in merged.entities
    assert "hallucinated_age_group" not in merged.dimensions
    assert "country" in merged.dimensions


def test_semantic_contract_omits_hallucinated_dimensions():
    """SemanticContractBuilder must not include ungrounded dimensions in the frozen contract."""
    contract = semantic_contract_builder.build_contract(
        question="Show total revenue by country and age_bracket",
        intent="database",
        route="data_query",
        candidate_tables=["customers", "orders"],
        raw_entities=["customers", "fake_table"],
        raw_metrics=["revenue"],
        raw_dimensions=["country", "fake_dimension_xyz"],
        raw_filters=[],
        raw_sorting=[],
        limit=10,
        schema=_MOCK_SCHEMA,
    )

    dim_cols = [d.source_column for d in contract.dimensions]
    assert "country" in dim_cols
    assert "fake_dimension_xyz" not in dim_cols
    assert contract.is_frozen is True


def test_schema_grounding_flags_unsupported_out_of_domain_queries():
    """SchemaGroundingEngine must flag out-of-domain/unsupported queries instead of silently picking arbitrary central tables."""
    from app.agent.schema_grounding.grounding_engine import SchemaGroundingEngine
    from unittest.mock import MagicMock

    engine = SchemaGroundingEngine(schema_service=MagicMock())
    
    # Large schema where no tables/columns match the question
    large_schema = {
        f"table_{i}": {
            "columns": [{"name": f"col_{i}_{j}", "type": "INTEGER"} for j in range(3)],
            "foreign_keys": [],
            "primary_key": [f"col_{i}_0"],
        }
        for i in range(15)
    }

    grounded = engine.build_grounded_schema(
        schema=large_schema,
        question="ما هي درجات الحرارة والطقس المتوقعة غداً؟",  # Completely off-domain
    )

    # Must be marked unsupported and ungrounded
    assert grounded.unsupported is True
    assert grounded.is_grounded is False
    assert grounded.unsupported_reason is not None

