import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.report_service import ReportService
from app.semantic.hybrid import HybridQueryUnderstander
from app.llm.model import _post_with_retry


@pytest.mark.asyncio
async def test_generate_report_and_chart_unified():
    """Verify generate_report_and_chart combines report generation and chart suggestion."""
    service = ReportService()
    results = [
        {"genre": "Rock", "tracks_count": 1200},
        {"genre": "Jazz", "tracks_count": 450},
        {"genre": "Metal", "tracks_count": 800},
    ]

    with patch.object(service, "generate_report", new_callable=AsyncMock) as mock_report:
        mock_report.return_value = "## Overview\nRock is the largest genre."
        
        report, chart = await service.generate_report_and_chart(
            question="What are top genres by track count?",
            sql="SELECT genre, count(*) FROM tracks GROUP BY genre",
            results=results,
            require_verification=False,
        )

        assert "Rock" in report
        assert isinstance(chart, dict)
        assert chart.get("should_chart") is True
        assert chart.get("chart_type") == "bar"
        assert chart.get("x_column") == "genre"
        assert chart.get("y_column") == "tracks_count"
        # Verify generate_report was called only once
        assert mock_report.call_count == 1


@pytest.mark.asyncio
async def test_hybrid_query_understanding_heuristic_fast_path():
    """Verify HybridQueryUnderstander uses fast 0-token path when confidence is high."""
    mock_llm = MagicMock()
    understander = HybridQueryUnderstander(fast_llm=mock_llm)
    schema = {
        "customers": {
            "columns": [
                {"name": "CustomerId", "type": "INTEGER"},
                {"name": "Country", "type": "VARCHAR"},
            ]
        }
    }

    # Query with matching table and column
    res = await understander.understand("How many customers are in Brazil?", schema=schema)
    assert res.source == "heuristic_fast_path"
    assert "customers" in res.entities
    # Fast LLM understander should NOT have been invoked
    if understander.llm_understander:
        assert understander.llm_understander.chain is None or mock_llm.ainvoke.call_count == 0


@pytest.mark.asyncio
async def test_post_with_retry_on_429():
    """Verify _post_with_retry retries on 429 status code and succeeds."""
    mock_client = AsyncMock()

    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    resp_429 = httpx.Response(status_code=429, headers={"retry-after": "0.1"}, request=req)
    resp_200 = httpx.Response(status_code=200, json={"choices": [{"message": {"content": "SELECT 1;"}}]}, request=req)
    mock_client.post.side_effect = [resp_429, resp_200]

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        resp = await _post_with_retry(
            mock_client,
            url="https://api.groq.com/openai/v1/chat/completions",
            headers={},
            json_payload={},
            max_retries=2,
            initial_delay=0.1,
        )

        assert resp.status_code == 200
        assert mock_client.post.call_count == 2
        assert mock_sleep.call_count == 1


@pytest.mark.asyncio
async def test_deterministic_report_zero_llm_calls():
    """Verify standard queries generate reports deterministically without calling LLM."""
    service = ReportService()
    results = [
        {"genre": "Rock", "total_sales": 1500.0},
        {"genre": "Jazz", "total_sales": 800.0},
    ]

    with patch("app.services.report_service.get_langchain_llm") as mock_get_llm:
        report = await service.generate_report(
            question="What are top genres by sales?",
            sql="SELECT genre, sum(sales) FROM tracks GROUP BY genre",
            results=results,
            require_verification=False,
        )

        assert "Rock" in report
        assert "Jazz" in report
        # Verify LLM was NOT invoked
        assert mock_get_llm.call_count == 0


@pytest.mark.asyncio
async def test_deterministic_report_scalar_and_lookup():
    """Verify scalar counts and entity lookups produce direct deterministic reports."""
    service = ReportService()

    with patch("app.services.report_service.get_langchain_llm") as mock_get_llm:
        # Scalar count
        rep_count = await service.generate_report(
            question="كم عدد العملاء؟",
            sql="SELECT count(*) as total FROM customers",
            results=[{"total": 59}],
            require_verification=False,
        )
        assert "59" in rep_count
        assert mock_get_llm.call_count == 0

        # Entity lookup
        rep_lookup = await service.generate_report(
            question="Get customer details for id 1",
            sql="SELECT name, email, country FROM customers WHERE id = 1",
            results=[{"name": "John Doe", "email": "john@example.com", "country": "USA"}],
            require_verification=False,
        )
        assert "John Doe" in rep_lookup
        assert "USA" in rep_lookup
        assert mock_get_llm.call_count == 0


@pytest.mark.asyncio
async def test_complex_analysis_attempts_single_sql_first():
    """Verify comparison/trend queries attempt single-pass SQL first, bypassing Planner."""
    from app.agents.analyst_agent import AnalystAgent

    agent = AnalystAgent()
    mock_db = MagicMock()

    # Mock schema service
    with patch.object(agent.schema_service, "get_database_context") as mock_get_ctx, \
         patch.object(agent.sql_generator, "generate_sql", new_callable=AsyncMock) as mock_gen_sql, \
         patch.object(agent.sql_generator, "execute_with_repair", new_callable=AsyncMock) as mock_exec, \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock) as mock_rep:

        mock_ctx = MagicMock()
        mock_ctx.schema = {"orders": {"columns": [{"name": "id", "type": "int"}, {"name": "total", "type": "float"}]}}
        mock_ctx.catalog = None
        mock_ctx.total_tables = 1
        mock_ctx.total_columns = 2
        mock_get_ctx.return_value = mock_ctx

        mock_gen_sql.return_value = "SELECT sum(total) FROM orders"
        mock_exec.return_value = ([{"sum": 1000.0}], "SELECT sum(total) FROM orders", None, None, [])
        mock_rep.return_value = ("Total is 1000", {})

        with patch("app.agents.analyst_agent.Planner") as mock_planner_cls:
            res = await agent.ask("Compare 2023 vs 2024 orders revenue", db=mock_db)

            assert res["success"] is True
            assert mock_gen_sql.call_count == 1
            # Verify Planner was NEVER invoked because single SQL succeeded!
            assert mock_planner_cls.call_count == 0


@pytest.mark.asyncio
async def test_langgraph_orchestrator_single_sql_and_direct_fallback():
    from app.agents.analyst_agent import AnalystAgent
    from app.config.settings import settings

    agent = AnalystAgent()
    mock_db = MagicMock()

    with patch.object(agent.schema_service, "get_database_context") as mock_get_ctx, \
         patch.object(agent.sql_generator, "generate_sql", new_callable=AsyncMock) as mock_gen_sql, \
         patch.object(agent.sql_generator, "execute_with_repair", new_callable=AsyncMock) as mock_exec:

        mock_ctx = MagicMock()
        mock_ctx.schema = {"users": {"columns": [{"name": "id", "type": "int"}, {"name": "name", "type": "varchar"}]}}
        mock_ctx.catalog = None
        mock_ctx.total_tables = 1
        mock_ctx.total_columns = 2
        mock_get_ctx.return_value = mock_ctx

        mock_gen_sql.return_value = "SELECT count(*) FROM users"
        mock_exec.return_value = ([{"count": 5}], "SELECT count(*) FROM users", None, None, [])

        with patch.object(settings, "use_langgraph_orchestrator", True):
            res = await agent.ask("How many users are there?", db=mock_db)

            assert res["success"] is True
            assert mock_gen_sql.call_count == 1
            assert res["results"] == [{"count": 5}]
