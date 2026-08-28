import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.services.sql.result_verifier import ResultVerifier, ResultVerificationOutcome
from app.agent.semantic.models import QueryUnderstanding, ExecutionRoute, OutputFormat
from app.utils.text_processor import AnalysisType
from app.agent.orchestration.analyst_agent import AnalystAgent
from app.models.schema_catalog.models import SchemaCatalog, TableProfile, ColumnProfile


def test_result_verifier_scalar_cardinality():
    """Verify ResultVerifier flags cardinality mismatch for scalar expectation."""
    verifier = ResultVerifier()

    query_spec = QueryUnderstanding(
        raw_question="How many users are there?",
        route=ExecutionRoute.DATA_QUERY,
        analysis_type=AnalysisType.COUNT,
        entities=["users"],
        metrics=["total_users"],
        expected_output=OutputFormat.SCALAR,
    )

    # 1 row, 1 col -> OK
    outcome = verifier.verify(
        rows=[{"total_users": 42}],
        query_spec=query_spec,
        sql="SELECT COUNT(*) as total_users FROM users",
    )
    assert outcome.passed is True
    assert outcome.cardinality_status == "ok"

    # Multiple rows for scalar -> Mismatch
    outcome_multi = verifier.verify(
        rows=[{"id": 1}, {"id": 2}, {"id": 3}],
        query_spec=query_spec,
        sql="SELECT id FROM users",
    )
    assert outcome_multi.cardinality_status == "cardinality_mismatch"
    assert any("scalar" in w for w in outcome_multi.warnings)


def test_result_verifier_all_null_columns():
    """Verify ResultVerifier flags when all rows have NULL in a column."""
    verifier = ResultVerifier()

    query_spec = QueryUnderstanding(
        raw_question="Show revenue trend",
        route=ExecutionRoute.DATA_QUERY,
        analysis_type=AnalysisType.TREND,
        entities=["revenue"],
    )

    outcome = verifier.verify(
        rows=[{"month": "Jan", "amount": None}, {"month": "Feb", "amount": None}],
        query_spec=query_spec,
        sql="SELECT month, amount FROM revenue",
    )
    assert outcome.null_behavior_status == "all_null_metrics"
    assert any("NULL" in w for w in outcome.warnings)


def test_result_verifier_hard_gates_block_semantic_failures():
    """Aggregate and QuerySpec failures must not be masked by other passing checks."""
    verifier = ResultVerifier()
    query_spec = QueryUnderstanding(
        raw_question="What is total revenue?",
        route=ExecutionRoute.DATA_QUERY,
        metrics=["revenue"],
    )

    outcome = verifier.verify(
        rows=[{"revenue": 100}, {"revenue": 200}],
        query_spec=query_spec,
        sql="SELECT revenue FROM sales",
        validation_status={"safety_valid": True, "identifiers_valid": True, "alignment_valid": False},
    )

    assert outcome.aggregate_semantics_valid is False
    assert outcome.gate_statuses["aggregate_semantics"] == "FAIL"
    assert outcome.gate_statuses["semantic_alignment"] == "FAIL"
    assert outcome.answer_action == "FAIL"
    assert outcome.passed is False


def test_result_verifier_warn_gate_keeps_answer_with_explicit_warning():
    verifier = ResultVerifier()
    outcome = verifier.verify(rows=[], sql="SELECT * FROM sales")

    assert outcome.gate_statuses["result_cardinality"] == "WARN"
    assert outcome.answer_action == "WARN"
    assert outcome.passed is True


def test_result_verifier_does_not_treat_duplicate_rows_as_cartesian_evidence():
    """Duplicate result values are normal without join-grain evidence."""
    verifier = ResultVerifier()

    # 20 rows with identical contents
    rows = [{"cust_id": 1, "order_id": 100}] * 20

    outcome = verifier.verify(
        rows=rows,
        sql="SELECT cust_id, order_id FROM customers JOIN orders",
    )
    assert outcome.duplicate_amplification_detected is False
    assert outcome.join_cardinality_status == "not_evaluated"


def test_result_verifier_detects_fk_backed_fanout_not_row_equality():
    verifier = ResultVerifier()
    catalog = SchemaCatalog(
        fingerprint="fanout", dialect="sqlite", database_name="test",
        tables={
            "customers": TableProfile(name="customers", primary_key=["customer_id"], columns=[ColumnProfile(name="customer_id", type="INT", primary_key=True)]),
            "orders": TableProfile(name="orders", primary_key=["order_id"], columns=[ColumnProfile(name="order_id", type="INT", primary_key=True)], foreign_keys=[{"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["customer_id"]}]),
            "contacts": TableProfile(name="contacts", primary_key=["contact_id"], columns=[ColumnProfile(name="contact_id", type="INT", primary_key=True)], foreign_keys=[{"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["customer_id"]}]),
        },
    )
    rows = [
        {"customer_id": 1, "order_id": order_id, "contact_id": contact_id}
        for order_id in (10, 11) for contact_id in (100, 101, 102)
    ]
    outcome = verifier.verify(
        rows=rows,
        sql="SELECT c.customer_id, o.order_id, x.contact_id FROM customers c JOIN orders o ON o.customer_id = c.customer_id JOIN contacts x ON x.customer_id = c.customer_id",
        catalog=catalog,
    )

    assert outcome.join_cardinality_status == "fanout_warning"
    assert outcome.metrics_summary["join_cardinality"]["row_multiplication_ratio"] == 2.0
    assert outcome.answer_action == "WARN"


@pytest.mark.asyncio
async def test_analyst_agent_12_step_execution_and_evaluation_trace():
    """Verify AnalystAgent executes the 12-step flow and records a complete evaluation trace."""
    agent = AnalystAgent()

    sample_rows = [{"total_sales": 15000}]

    mock_ctx = MagicMock()
    mock_ctx.schema = {"sales": {"columns": [{"name": "amount", "type": "float"}]}}
    mock_ctx.catalog = None
    mock_ctx.total_tables = 1
    mock_ctx.total_columns = 1

    with patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.sql_generator, "generate_sql", new_callable=AsyncMock) as mock_gen_sql, \
         patch.object(agent.sql_generator, "execute_with_repair", new_callable=AsyncMock) as mock_exec, \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock) as mock_report:

        mock_gen_sql.return_value = "SELECT SUM(amount) as total_sales FROM sales"
        mock_exec.return_value = (sample_rows, "SELECT SUM(amount) as total_sales FROM sales", None, None, [])
        mock_report.return_value = ("Total sales are $15,000.", None)

        res = await agent.ask(
            question="What is the total sales amount?",
            session_id="test_session_12_step",
            db=MagicMock(),
        )

        assert res["success"] is True
        assert "evaluation_trace" in res

        trace = res["evaluation_trace"]
        assert trace["question"] == "What is the total sales amount?"
        assert trace["route"] in ("data_query", "database", "database_query")
        assert "retrieval_evidence" in trace
        assert "query_spec" in trace
        assert "sql" in trace
        assert "validation_passed" in trace
        assert "execution_metrics" in trace
        assert trace["execution_metrics"]["rows_count"] == 1
        assert "verification_outcome" in trace
        assert trace["verification_outcome"]["passed"] is True
