import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from app.services.sql.validator import SQLValidator
from app.services.sql.result_verifier import ResultVerifier
from app.agent.semantic.models import QueryUnderstanding, ExecutionRoute, OutputFormat
from app.utils.text_processor import AnalysisType
from app.models.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile
from app.agent.orchestration.analyst_agent import AnalystAgent


def create_mock_catalog():
    return SchemaCatalog(
        fingerprint="quality_fp",
        dialect="sqlite",
        database_name="QualityDB",
        tables={
            "customers": TableProfile(
                name="customers",
                columns=[
                    ColumnProfile(name="customer_id", type="INTEGER", primary_key=True),
                    ColumnProfile(name="customer_name", type="VARCHAR"),
                ],
                foreign_keys=[],
            ),
            "orders": TableProfile(
                name="orders",
                columns=[
                    ColumnProfile(name="order_id", type="INTEGER", primary_key=True),
                    ColumnProfile(name="customer_id", type="INTEGER", is_foreign_key=True),
                    ColumnProfile(name="amount", type="REAL"),
                ],
                foreign_keys=[
                    {"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["customer_id"]}
                ],
            ),
        }
    )


def test_control_1_identifier_grounding():
    """Verify Control 1: Identifier Grounding rejects non-existent tables/columns."""
    validator = SQLValidator()
    catalog = create_mock_catalog()

    # Valid query
    ok, warns = validator.verify_sql_identifiers(
        "SELECT customer_name, amount FROM customers JOIN orders ON customers.customer_id = orders.customer_id",
        catalog=catalog,
    )
    assert ok is True
    assert len(warns) == 0

    # Hallucinated table 'inventories'
    ok_bad_tab, warns_tab = validator.verify_sql_identifiers(
        "SELECT customer_name FROM inventories",
        catalog=catalog,
    )
    assert ok_bad_tab is False
    assert any("inventories" in w for w in warns_tab)

    # Hallucinated column 'discount_code' on customers
    ok_bad_col, warns_col = validator.verify_sql_identifiers(
        "SELECT discount_code FROM customers",
        catalog=catalog,
    )
    assert ok_bad_col is False
    assert any("discount_code" in w for w in warns_col)


def test_control_2_join_path_verification():
    """Verify Control 2: Join Path Verification ensures join edges match catalog foreign keys."""
    validator = SQLValidator()
    catalog = create_mock_catalog()

    # Valid join between orders and customers
    ok_valid, warns_valid = validator.verify_sql_joins(
        "SELECT * FROM orders JOIN customers ON orders.customer_id = customers.customer_id",
        catalog=catalog,
    )
    assert ok_valid is True
    assert len(warns_valid) == 0

    # Tables are connected, but these are not the FK columns. Connectivity
    # alone must not make the JOIN semantically valid.
    ok_wrong_key, warns_wrong_key = validator.verify_sql_joins(
        "SELECT * FROM orders JOIN customers ON orders.order_id = customers.customer_id",
        catalog=catalog,
    )
    assert ok_wrong_key is False
    assert any("ON key" in w for w in warns_wrong_key)

    # Invalid join between orders and an unlinked table
    ok_bad, warns_bad = validator.verify_sql_joins(
        "SELECT * FROM orders JOIN products ON orders.order_id = products.product_id",
        catalog=catalog,
    )
    assert ok_bad is False
    assert any("products" in w for w in warns_bad)


def test_control_3_query_spec_to_sql_alignment():
    """Verify Control 3: QuerySpec-to-SQL checker flags missing metrics or filters."""
    validator = SQLValidator()

    query_spec = QueryUnderstanding(
        raw_question="What is the total revenue by customer?",
        route=ExecutionRoute.DATA_QUERY,
        analysis_type=AnalysisType.AGGREGATION,
        entities=["orders"],
        metrics=["total_revenue"],
        dimensions=["customer_name"],
    )

    # SQL with missing GROUP BY when dimensions are requested
    ok_missing_group, warns_group = validator.verify_query_spec_alignment(
        "SELECT SUM(amount) FROM orders",
        query_spec=query_spec,
    )
    assert ok_missing_group is False
    assert any("GROUP BY" in w for w in warns_group)

    # SQL with aggregations and group by -> OK
    ok_aligned, warns_aligned = validator.verify_query_spec_alignment(
        "SELECT customer_name, SUM(amount) FROM orders JOIN customers ON orders.customer_id = customers.customer_id GROUP BY customer_name",
        query_spec=query_spec,
    )
    assert ok_aligned is True


def test_control_4_result_to_answer_claim_checker():
    """Verify Control 4: Result-to-Answer claim checker catches hallucinated numbers in narrative text."""
    verifier = ResultVerifier()

    rows = [{"customer": "Acme", "revenue": 15000.50}, {"customer": "Beta", "revenue": 2200.00}]
    analytics = {"total_sum": 17200.50, "row_count": 2}

    # Factual report with numbers grounded in rows/analytics
    valid_report = "Acme generated $15,000.50 and Beta generated $2,200.00, bringing total to 17,200.50 across 2 customers."
    ok, warns = verifier.verify_report_claims(valid_report, rows=rows, analytics_result=analytics)
    assert ok is True
    assert len(warns) == 0

    # Hallucinated report introducing fabricated $99,999.00
    hallucinated_report = "Acme generated $15,000.50 while top tier accounts hit $99,999.00 in profit."
    ok_bad, warns_bad = verifier.verify_report_claims(hallucinated_report, rows=rows, analytics_result=analytics)
    assert ok_bad is False
    assert any("99,999" in w or "99999" in w for w in warns_bad)


@pytest.mark.asyncio
async def test_controls_5_6_7_confidence_decomposition_and_bilingual_policy():
    """Verify Controls 5, 6, 7 in AnalystAgent: 6-part confidence decomposition and deterministic scope gate."""
    agent = AnalystAgent()

    # 1. Test Arabic Out-of-Domain Scope Gate (Control 7)
    ar_res = await agent.ask("ما هو الطقس في القاهرة اليوم؟", session_id="test_ar", db=MagicMock())
    assert ar_res["intent"] == "conversation"
    assert "قواعد البيانات" in ar_res["report"]  # Database-scoped Arabic message

    # 2. Test English Out-of-Domain Scope Gate (Control 7)
    en_res = await agent.ask("What is the capital of France?", session_id="test_en", db=MagicMock())
    assert en_res["intent"] == "conversation"
    assert "database" in en_res["report"].lower()  # Database-scoped English message

    # 3. Test Full Pipeline Confidence Decomposition (Control 6)
    mock_ctx = MagicMock()
    mock_ctx.schema = {"users": {"columns": [{"name": "id", "type": "int"}]}}
    mock_ctx.catalog = None
    mock_ctx.total_tables = 1
    mock_ctx.total_columns = 1

    with patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.sql_generator, "generate_sql", new_callable=AsyncMock) as mock_gen_sql, \
         patch.object(agent.sql_generator, "execute_with_repair", new_callable=AsyncMock) as mock_exec, \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock) as mock_report:

        mock_gen_sql.return_value = "SELECT COUNT(*) as count FROM users"
        mock_exec.return_value = ([{"count": 50}], "SELECT COUNT(*) as count FROM users", None, None, [])
        mock_report.return_value = ("There are 50 total users in the system.", None)

        res = await agent.ask("How many users exist in the database?", session_id="test_conf", db=MagicMock())

        assert res["success"] is True
        assert "confidence_breakdown" in res

        cb = res["confidence_breakdown"]
        assert "route" in cb
        assert "retrieval" in cb
        assert "grounding" in cb
        assert "sql" in cb
        assert "execution" in cb
        assert "answer" in cb
        assert "overall" in cb
        assert 0.0 <= cb["overall"] <= 1.0
