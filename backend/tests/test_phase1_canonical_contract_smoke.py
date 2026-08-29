"""Phase 1 Smoke Test — Contract Stabilization & Scope Gate Verification."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.agent.semantic.models import QueryUnderstanding, ExecutionRoute, IntentType
from app.utils.helpers import AnalysisType
from app.agent.semantic.query_spec_builder import QuerySpecBuilder
from app.agent.orchestration.intent_classifier import IntentClassifier
from app.agent.semantic.hybrid import HybridQueryUnderstander
from app.agent.orchestration.analyst_agent import AnalystAgent
from app.core.config.settings import settings


def test_phase1_query_spec_canonical_contract():
    """Verify QuerySpec is the single unified contract for semantic routing."""
    builder = QuerySpecBuilder()

    # 1. Database Query produces QuerySpec with metrics/aggregations and filters
    spec_db = builder.build_spec("Show total revenue by country for 2024")
    assert spec_db.route == ExecutionRoute.DATA_QUERY
    assert spec_db.intent == IntentType.DATABASE
    assert "SUM" in spec_db.aggregations
    assert len(spec_db.filters) >= 1 or len(spec_db.time_expressions) >= 1

    # 2. Schema Query produces QuerySpec
    spec_schema = builder.build_spec("What tables are available in the schema?")
    assert spec_schema.route == ExecutionRoute.SCHEMA
    assert spec_schema.intent == IntentType.SCHEMA

    # 3. Off-topic produces QuerySpec
    spec_off = builder.build_spec("What is the capital of Italy?")
    assert spec_off.route == ExecutionRoute.CONVERSATION
    assert spec_off.intent == IntentType.OFF_TOPIC


@pytest.mark.asyncio
async def test_phase1_deterministic_scope_gate_no_chatbot():
    """Verify unsupported/general questions are strictly routed to deterministic database-scoped messages."""
    agent = AnalystAgent()

    # English off-topic
    res_en = await agent.ask("Tell me a bedtime story about dragons", session_id="smoke_en", db=MagicMock())
    assert res_en["intent"] == "conversation"
    assert "database" in res_en["report"].lower()
    # Ensure no SQL was attempted
    assert res_en.get("sql", "") == ""

    # Arabic off-topic
    res_ar = await agent.ask("ما هي عاصمة فرنسا؟", session_id="smoke_ar", db=MagicMock())
    assert res_ar["intent"] == "conversation"
    assert "قواعد البيانات" in res_ar["report"]
    assert res_ar.get("sql", "") == ""


@pytest.mark.asyncio
async def test_phase1_adapters_delegate_to_canonical_query_spec():
    """Verify legacy IntentClassifier and HybridQueryUnderstander adapt to QuerySpecBuilder."""
    classifier = IntentClassifier()
    intent_res = await classifier.classify_intent("Calculate total revenue by country")
    assert intent_res["intent"] == "database"
    assert "Canonical QuerySpec" in intent_res["reasoning"]

    understander = HybridQueryUnderstander()
    spec = await understander.understand("Calculate total revenue by country")
    assert isinstance(spec, QueryUnderstanding)
    assert spec.route == ExecutionRoute.DATA_QUERY


@pytest.mark.asyncio
async def test_phase1_end_to_end_smoke_pipeline():
    """End-to-end smoke test through the full 12-step pipeline."""
    agent = AnalystAgent()

    mock_ctx = MagicMock()
    mock_ctx.schema = {
        "users": {"columns": [{"name": "active", "type": "boolean"}]}
    }
    mock_ctx.catalog = None
    mock_ctx.total_tables = 1
    mock_ctx.total_columns = 1

    grounded = MagicMock()
    grounded.schema_text = "users(active)"
    grounded.selected_tables = ["users"]
    grounded.selected_columns = {"users": ["active"]}
    grounded.retrieved_seed_tables = ["users"]
    grounded.timings_ms = {}
    grounded.fallback_used = False

    with patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock) as mock_ground, \
         patch.object(agent.sql_generator, "generate_sql", new_callable=AsyncMock) as mock_sql, \
         patch.object(agent.sql_generator, "execute_with_repair", new_callable=AsyncMock) as mock_exec, \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock) as mock_report:

        mock_ground.return_value = grounded
        mock_sql.return_value = "SELECT COUNT(*) as active_users FROM users WHERE active = True"
        mock_exec.return_value = ([{"active_users": 150}], "SELECT COUNT(*) as active_users FROM users WHERE active = True", None, None, [])
        mock_report.return_value = ("There are 150 active users in the database.", None)

        res = await agent.ask("How many active users are in the system?", session_id="e2e_smoke", db=MagicMock())

        assert res["success"] is True
        assert res["sql"] == "SELECT COUNT(*) as active_users FROM users WHERE active = True"
        assert res["results"] == [{"active_users": 150}]
        assert "150" in res["report"] and "active users" in res["report"]
        assert "evaluation_trace" in res
        assert res["confidence_breakdown"]["overall"] > 0.8


@pytest.mark.asyncio
async def test_service_pipeline_wires_llm_understanding_into_main_path():
    agent = AnalystAgent()
    mock_db = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.schema = {
        "orders": {"columns": [{"name": "total_amount", "type": "float"}, {"name": "country", "type": "varchar"}]}
    }
    mock_ctx.catalog = None
    mock_ctx.total_tables = 1
    mock_ctx.total_columns = 2

    grounded = MagicMock()
    grounded.schema_text = "orders(total_amount, country)"
    grounded.selected_tables = ["orders"]
    grounded.selected_columns = {"orders": ["total_amount", "country"]}
    grounded.retrieved_seed_tables = ["orders"]
    grounded.timings_ms = {}
    grounded.fallback_used = False

    llm_spec = QueryUnderstanding(
        raw_question="What is the total revenue by country?",
        intent=IntentType.DATABASE,
        route=ExecutionRoute.DATA_QUERY,
        route_confidence=0.9,
        analysis_type=AnalysisType.AGGREGATION,
        entities=["orders"],
        metrics=["orders.total_amount"],
        dimensions=["orders.country"],
        aggregations=["SUM"],
        confidence=0.9,
        source="llm_understanding",
    )

    with patch.object(settings, "use_llm_understanding", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder.llm_understander, "understand", new_callable=AsyncMock) as mock_understand, \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock) as mock_ground, \
         patch.object(agent.sql_generator, "generate_sql", new_callable=AsyncMock) as mock_sql, \
         patch.object(agent.sql_generator, "execute_with_repair", new_callable=AsyncMock) as mock_exec, \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock) as mock_report:

        mock_understand.return_value = llm_spec
        mock_ground.return_value = grounded
        mock_sql.return_value = "SELECT country, SUM(total_amount) AS total_revenue FROM orders GROUP BY country"
        mock_exec.return_value = ([{"country": "EG", "total_revenue": 1000.0}], mock_sql.return_value, None, None, [])
        mock_report.return_value = ("Revenue by country is available.", {})

        res = await agent.ask("What is the total revenue by country?", db=mock_db)

    assert res["success"] is True
    assert mock_understand.await_count >= 1
    assert mock_ground.await_args.kwargs["query_understanding"].source == "llm_query_spec_builder"


@pytest.mark.asyncio
async def test_langgraph_pipeline_wires_llm_understanding_into_main_path():
    agent = AnalystAgent()
    mock_db = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.schema = {
        "orders": {"columns": [{"name": "total_amount", "type": "float"}, {"name": "country", "type": "varchar"}]}
    }
    mock_ctx.catalog = None
    mock_ctx.total_tables = 1
    mock_ctx.total_columns = 2

    grounded = MagicMock()
    grounded.schema_text = "orders(total_amount, country)"
    grounded.selected_tables = ["orders"]
    grounded.selected_columns = {"orders": ["total_amount", "country"]}
    grounded.retrieved_seed_tables = ["orders"]
    grounded.timings_ms = {}
    grounded.fallback_used = False

    llm_spec = QueryUnderstanding(
        raw_question="What is the total revenue by country?",
        intent=IntentType.DATABASE,
        route=ExecutionRoute.DATA_QUERY,
        route_confidence=0.9,
        analysis_type=AnalysisType.AGGREGATION,
        entities=["orders"],
        metrics=["orders.total_amount"],
        dimensions=["orders.country"],
        aggregations=["SUM"],
        confidence=0.9,
        source="llm_understanding",
    )

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(settings, "use_llm_understanding", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder.llm_understander, "understand", new_callable=AsyncMock) as mock_understand, \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock) as mock_ground, \
         patch.object(agent.sql_generator, "generate_sql", new_callable=AsyncMock) as mock_sql, \
         patch.object(agent.sql_generator, "execute_with_repair", new_callable=AsyncMock) as mock_exec, \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock) as mock_report:

        mock_understand.return_value = llm_spec
        mock_ground.return_value = grounded
        mock_sql.return_value = "SELECT country, SUM(total_amount) AS total_revenue FROM orders GROUP BY country"
        mock_exec.return_value = ([{"country": "EG", "total_revenue": 1000.0}], mock_sql.return_value, None, None, [])
        mock_report.return_value = ("Revenue by country is available.", {})

        res = await agent.ask("What is the total revenue by country?", db=mock_db)

    assert res["success"] is True
    assert mock_understand.await_count >= 1
    assert mock_ground.await_args.kwargs["query_understanding"].source == "llm_query_spec_builder"
