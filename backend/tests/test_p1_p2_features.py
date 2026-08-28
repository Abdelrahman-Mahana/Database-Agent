import pytest
from unittest.mock import MagicMock, patch

from app.agent.schema_intelligence.semantic_classifier import infer_semantic_type, SemanticType
from app.agent.semantic.ambiguity_resolver import AmbiguityResolver
from app.services.query_explain_service import QueryExplainService
from app.services.template_service import TemplateService, QueryTemplate
from app.services.feedback_service import FeedbackService
from app.models.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile


def test_semantic_data_types_classification():
    """Verify inference of high-level semantic business types."""
    assert infer_semantic_type("total_amount", "DECIMAL(10,2)") == SemanticType.MONEY
    assert infer_semantic_type("unit_price", "REAL") == SemanticType.MONEY
    assert infer_semantic_type("customer_id", "INTEGER") == SemanticType.IDENTIFIER
    assert infer_semantic_type("created_at", "TIMESTAMP") == SemanticType.DATE
    assert infer_semantic_type("profit_margin_pct", "REAL") == SemanticType.PERCENTAGE
    assert infer_semantic_type("order_status", "VARCHAR(20)") == SemanticType.STATUS
    assert infer_semantic_type("country_code", "VARCHAR(3)") == SemanticType.GEOGRAPHY
    assert infer_semantic_type("item_quantity", "INTEGER") == SemanticType.COUNT
    assert infer_semantic_type("notes_and_comments", "TEXT") == SemanticType.FREE_TEXT
    assert infer_semantic_type("category_type", "VARCHAR(50)") == SemanticType.CATEGORY


def test_ambiguity_resolver_detects_close_candidates():
    """Verify AmbiguityResolver flags ambiguous table matches with close confidence scores."""
    resolver = AmbiguityResolver()

    # Ambiguous competing tables
    candidates = [
        {"name": "orders", "score": 0.85, "reason": "Lexical match for 'orders'"},
        {"name": "order_archive", "score": 0.80, "reason": "Semantic match for 'orders'"},
    ]

    res = resolver.resolve_table_ambiguity("Show all orders", candidates, threshold_margin=0.10)
    assert res.is_ambiguous is True
    assert res.clarification_prompt is not None
    assert "orders" in res.clarification_prompt
    assert "order_archive" in res.clarification_prompt

    # Dominant single table
    clear_candidates = [
        {"name": "customers", "score": 0.95},
        {"name": "logs", "score": 0.10},
    ]
    res_clear = resolver.resolve_table_ambiguity("Show customers", clear_candidates, threshold_margin=0.10)
    assert res_clear.is_ambiguous is False
    assert res_clear.chosen_candidate == "customers"


def test_query_explain_service_dry_run_analysis():
    """Verify QueryExplainService generates full breakdown of SQL tables, joins, filters, and safety."""
    explainer = QueryExplainService()

    sql = """
    SELECT c.customer_name, SUM(o.total_amount) as revenue
    FROM customers c
    JOIN orders o ON c.customer_id = o.customer_id
    WHERE o.order_date >= '2024-01-01'
    GROUP BY c.customer_name
    """

    explanation = explainer.explain_sql(sql)

    assert explanation["safety_valid"] is True
    assert "customers" in explanation["tables_used"]
    assert "orders" in explanation["tables_used"]
    assert len(explanation["join_paths"]) >= 1
    assert any("orders" in j["table"] for j in explanation["join_paths"])
    assert len(explanation["filters"]) >= 1
    assert any("SUM" in agg for agg in explanation["aggregations"])


def test_template_service_render_and_execute():
    """Verify QueryTemplate registration, parameter substitution, and execution."""
    service = TemplateService()

    template = QueryTemplate(
        template_id="monthly_sales_by_region",
        title="Monthly Sales by Region",
        description="Calculates total revenue filtered by region and year",
        sql_template="SELECT SUM(amount) FROM sales WHERE region = :region AND year = :year",
        parameters=["region", "year"],
        default_values={"year": 2024},
        tags=["sales", "finance"],
    )
    service.register_template(template)

    # Render SQL
    rendered = service.render_sql("monthly_sales_by_region", {"region": "EMEA"})
    assert "region = 'EMEA'" in rendered
    assert "year = 2024" in rendered

    # Execute with mock db
    mock_db = MagicMock()
    with patch.object(service.sql_executor, "execute") as mock_exec:
        mock_exec.return_value = [{"total": 50000}]
        rows = service.execute_template("monthly_sales_by_region", {"region": "EMEA"}, db=mock_db, use_cache=False)
        assert rows[0]["total"] == 50000


def test_feedback_service_updates_catalog_synonyms(tmp_path, monkeypatch):
    """Verify FeedbackService updates catalog synonyms and persists changes to disk."""
    monkeypatch.setattr("app.models.schema_catalog.catalog_builder.CATALOG_DIR", tmp_path)

    catalog = SchemaCatalog(
        fingerprint="feedback_test_fp",
        dialect="sqlite",
        database_name="FeedbackDB",
        tables={
            "clients": TableProfile(
                name="clients",
                columns=[ColumnProfile(name="client_name", type="VARCHAR")],
                synonyms=["customers"],
            )
        }
    )

    feedback = FeedbackService()
    # Add new table synonym "buyers"
    feedback.record_term_synonym(catalog, target_entity="table", target_name="clients", synonym="buyers")
    assert "buyers" in catalog.tables["clients"].synonyms

    # Add column synonym "full_name"
    feedback.record_term_synonym(catalog, target_entity="column", target_name="clients.client_name", synonym="full_name")
    assert "full_name" in catalog.tables["clients"].columns[0].synonyms
