"""Unit tests for the upgraded LangGraph Analytical Orchestrator flow."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.orchestration.analyst_agent import AnalystAgent
from app.core.config.settings import settings
from app.agent.semantic.models import ExecutionRoute, IntentType, QueryUnderstanding
from app.utils.helpers import AnalysisType


@pytest.mark.asyncio
async def test_langgraph_analytical_flow_end_to_end():
    agent = AnalystAgent()
    mock_db = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.schema = {
        "sales": {
            "columns": [
                {"name": "revenue", "type": "float"},
                {"name": "region", "type": "varchar"},
            ]
        }
    }
    mock_ctx.catalog = None
    mock_ctx.total_tables = 1
    mock_ctx.total_columns = 2

    grounded = MagicMock()
    grounded.schema_text = "sales(revenue, region)"
    grounded.selected_tables = ["sales"]
    grounded.selected_columns = {"sales": ["revenue", "region"]}
    grounded.retrieved_seed_tables = ["sales"]
    grounded.timings_ms = {}
    grounded.fallback_used = False

    spec = QueryUnderstanding(
        raw_question="قارن المبيعات بين المناطق",
        intent=IntentType.DATABASE,
        route=ExecutionRoute.DATA_QUERY,
        route_confidence=0.95,
        analysis_type=AnalysisType.COMPARISON,
        entities=["sales"],
        metrics=["sales.revenue"],
        dimensions=["sales.region"],
        aggregations=["SUM"],
        confidence=0.95,
        source="deterministic",
    )

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock) as mock_spec_builder, \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock) as mock_ground, \
         patch.object(agent.sql_generator, "generate_sql", new_callable=AsyncMock) as mock_sql, \
         patch.object(agent.sql_generator, "execute_with_repair", new_callable=AsyncMock) as mock_exec, \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock) as mock_report:

        mock_spec_builder.return_value = spec
        mock_ground.return_value = grounded
        mock_sql.return_value = "SELECT region, SUM(revenue) AS total_rev FROM sales GROUP BY region"
        mock_exec.return_value = (
            [{"region": "Cairo", "total_rev": 5000.0}, {"region": "Alex", "total_rev": 3000.0}],
            mock_sql.return_value,
            None,
            None,
            [],
        )
        mock_report.return_value = ("مقارنة المبيعات بين القاهرة والإسكندرية متوفرة.", {"type": "bar"})

        res = await agent.ask("قارن المبيعات بين المناطق", db=mock_db)

    assert res["success"] is True
    assert "analysis_planning_ms" in res.get("timings_ms", {})
    assert "analysis_plan_summary" in res
    assert res["analysis_plan_summary"]["primary_operation"] == "compare"
    assert len(res["results"]) == 2
    assert res["sql"] == "SELECT region, SUM(revenue) AS total_rev FROM sales GROUP BY region"
    assert "verification" in res


@pytest.mark.asyncio
async def test_langgraph_offtopic_route_short_circuit():
    agent = AnalystAgent()
    mock_db = MagicMock()

    with patch.object(settings, "use_langgraph_orchestrator", True):
        res = await agent.ask("What is the speed of light in vacuum?", db=mock_db)

    assert res["intent"] == "conversation"
    assert res["sql"] == ""
    assert res["success"] is True
    assert "database" in res["report"].lower()
