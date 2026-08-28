"""Tests for Enterprise Business Metric Registry and Semantic Decoupling."""
import pytest
from app.agent.semantic.contract import FormulaType
from app.agent.semantic.metric_registry import BusinessMetricRegistry, BusinessMetricDefinition, business_metric_registry
from app.agent.semantic.query_spec_builder import QuerySpecBuilder
from app.services.sql.prompt_builder import SQLPromptBuilder
from app.services.database.context import DatabaseContext


@pytest.fixture
def sample_schema():
    return {
        "invoices": {
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "total", "type": "FLOAT"},
                {"name": "customer_id", "type": "INTEGER"},
                {"name": "created_at", "type": "TIMESTAMP"},
            ]
        },
        "invoice_lines": {
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "invoice_id", "type": "INTEGER"},
                {"name": "quantity", "type": "INTEGER"},
                {"name": "unit_price", "type": "FLOAT"},
            ]
        },
        "customers": {
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "name", "type": "VARCHAR"},
                {"name": "country", "type": "VARCHAR"},
            ]
        },
    }


def test_metric_registry_resolves_english_business_concepts(sample_schema):
    """Test resolving English business concept 'total revenue' into SUM(invoices.total)."""
    registry = BusinessMetricRegistry()

    metrics = registry.resolve_metrics("What is our total revenue for 2024?", schema=sample_schema)
    assert len(metrics) >= 1
    rev = next((m for m in metrics if m.metric_id == "revenue"), None)
    assert rev is not None
    assert rev.source_table == "invoices"
    assert rev.source_column == "total"
    assert rev.expression == "SUM(invoices.total)"
    assert rev.unit == "currency"


def test_metric_registry_resolves_arabic_business_concepts(sample_schema):
    """Test resolving Arabic business concepts 'إجمالي الإيرادات', 'متوسط الفاتورة', 'عدد العملاء'."""
    registry = BusinessMetricRegistry()

    # 1. Arabic Revenue
    m_rev = registry.resolve_metric("كم إجمالي الإيرادات؟", schema=sample_schema)
    assert m_rev is not None
    assert m_rev.metric_id == "revenue"
    assert m_rev.source_table == "invoices"
    assert m_rev.source_column == "total"
    assert m_rev.expression == "SUM(invoices.total)"

    # 2. Arabic AOV
    m_aov = registry.resolve_metric("ما هو متوسط الفاتورة؟", schema=sample_schema)
    assert m_aov is not None
    assert m_aov.metric_id == "average_order_value"
    assert m_aov.source_table == "invoices"
    assert m_aov.source_column == "total"
    assert m_aov.expression == "AVG(invoices.total)"

    # 3. Arabic Customer Count
    m_cust = registry.resolve_metric("كم عدد العملاء؟", schema=sample_schema)
    assert m_cust is not None
    assert m_cust.metric_id == "customer_count"
    assert m_cust.requires_distinct is True
    assert "COUNT(DISTINCT" in m_cust.expression


def test_metric_registry_resolves_multiple_metrics_in_one_query(sample_schema):
    """Test extracting multiple metrics from a single query (e.g. revenue and quantity sold)."""
    registry = BusinessMetricRegistry()

    metrics = registry.resolve_metrics(
        "Show me total revenue and quantity sold by country",
        schema=sample_schema,
    )
    metric_ids = {m.metric_id for m in metrics}
    assert "revenue" in metric_ids
    assert "quantity_sold" in metric_ids


def test_custom_metric_registration(sample_schema):
    """Test dynamically registering a custom enterprise metric."""
    registry = BusinessMetricRegistry()

    registry.register_custom_metric(
        metric_id="active_subscribers",
        display_name="Active Subscribers",
        display_name_ar="المشتركين النشطين",
        formula_type=FormulaType.COUNT_DISTINCT,
        aliases_en=["active subscribers", "current subscribers", "mrr subscribers"],
        aliases_ar=["المشتركين النشطين", "عدد المشتركين"],
        candidate_columns=["customer_id", "id"],
        candidate_tables=["invoices", "customers"],
        unit="count",
        description="Number of paying subscribers with active status.",
    )

    metric = registry.resolve_metric("how many active subscribers do we have?", schema=sample_schema)
    assert metric is not None
    assert metric.metric_id == "active_subscribers"
    assert metric.requires_distinct is True


def test_query_spec_builder_populates_target_metrics(sample_schema):
    """Test that QuerySpecBuilder correctly identifies and attaches target_metrics."""
    builder = QuerySpecBuilder()
    db_ctx = DatabaseContext(
        engine=None,
        url="sqlite:///:memory:",
        database_name="test_db",
        fingerprint="fp_test",
        schema=sample_schema,
        table_names_set={"invoices", "invoice_lines", "customers"},
        total_tables=3,
        total_columns=11,
    )

    spec = builder.build_spec("ما هو إجمالي الإيرادات لكل دولة؟", db_ctx=db_ctx)
    assert len(spec.target_metrics) >= 1
    rev_metric = spec.target_metrics[0]
    assert rev_metric.metric_id == "revenue"
    assert rev_metric.source_table == "invoices"
    assert rev_metric.source_column == "total"


def test_prompt_builder_injects_verified_business_metrics(sample_schema):
    """Test that SQLPromptBuilder formats verified business metrics into the generation prompt."""
    builder = QuerySpecBuilder()
    prompt_builder = SQLPromptBuilder()

    db_ctx = DatabaseContext(
        engine=None,
        url="sqlite:///:memory:",
        database_name="test_db",
        fingerprint="fp_test",
        schema=sample_schema,
        table_names_set={"invoices", "invoice_lines", "customers"},
        total_tables=3,
        total_columns=11,
    )

    spec = builder.build_spec("Calculate total sales and average order value", db_ctx=db_ctx)
    prompt_input = prompt_builder.build_generation_input(
        schema_text="CREATE TABLE invoices (id INT, total FLOAT);",
        question="Calculate total sales and average order value",
        query_understanding=spec,
        dialect="sqlite",
        db_identifier="test_db",
    )

    context_str = prompt_input.get("conversation_history", "")
    assert "Required Measures / Aggregations" in context_str
    assert "invoices.total" in context_str
