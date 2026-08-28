"""Integration tests verifying QuerySpec/AnalysisPlan routing in the Analytics pipeline."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.orchestration.analyst_agent import AnalystAgent
from app.services.analytics.insight_engine import InsightEngine
from app.services.analytics.models import AnalyticsResult, DatasetSummary
from app.services.analysis.models import AnalysisResult
from app.agent.semantic.models import QuerySpec, AnalysisType


@pytest.mark.asyncio
async def test_analyst_agent_trend_query_executes_trend_analyzer_not_profiling():
    """Verify that a trend question executes TrendAnalyzer and produces trend findings and metrics."""
    agent = AnalystAgent()
    mock_db = MagicMock()

    # Time series rows for monthly sales
    sample_rows = [
        {"period": "2024-01", "sales": 1000.0},
        {"period": "2024-02", "sales": 1250.0},
        {"period": "2024-03", "sales": 1100.0},
        {"period": "2024-04", "sales": 2000.0},
    ]

    with patch.object(agent.schema_service, "get_database_context") as mock_get_ctx, \
         patch.object(agent.sql_generator, "generate_sql", new_callable=AsyncMock) as mock_gen_sql, \
         patch.object(agent.sql_generator, "execute_with_repair", new_callable=AsyncMock) as mock_exec, \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock) as mock_rep, \
         patch("app.core.config.settings.settings.use_llm_understanding", False):

        mock_rep.return_value = ("Sample trend report", None)
        mock_ctx = MagicMock()
        mock_ctx.schema = {
            "sales_monthly": {
                "columns": [
                    {"name": "period", "type": "varchar"},
                    {"name": "sales", "type": "float"},
                ]
            }
        }
        mock_ctx.catalog = None
        mock_ctx.total_tables = 1
        mock_ctx.total_columns = 2
        mock_get_ctx.return_value = mock_ctx

        mock_gen_sql.return_value = "SELECT period, sum(sales) as sales FROM sales_monthly GROUP BY period ORDER BY period"
        mock_exec.return_value = (sample_rows, "SELECT period, sum(sales) as sales FROM sales_monthly GROUP BY period ORDER BY period", None, None, [])

        res = await agent.ask("ما هو اتجاه المبيعات الشهرية خلال عام 2024؟", db=mock_db)

        assert res["success"] is True
        assert "analysis_plan_summary" in res
        assert res["analysis_plan_summary"]["analysis_type"] == "trend"

        # Verify unified analysis result
        assert "analysis_result" in res
        analysis_res = res["analysis_result"]
        assert analysis_res["analysis_type"] == "trend"

        # Verify domain findings are populated (not empty generic profiling)
        assert len(analysis_res["findings"]) > 0
        assert any("growth" in f.lower() or "اتجاه" in f or "معدل" in f or "trajectory" in f.lower() or "+" in f for f in analysis_res["findings"])

        # Verify domain metrics from TrendEngine are captured
        assert "overall_growth_pct" in analysis_res["metrics"]
        assert analysis_res["metrics"]["overall_growth_pct"] == 100.0
        assert analysis_res["metrics"].get("peak_period") == "2024-04"


@pytest.mark.asyncio
async def test_analyst_agent_correlation_query_executes_correlation_analyzer():
    """Verify that a correlation question executes CorrelationAnalyzer."""
    agent = AnalystAgent()
    mock_db = MagicMock()

    sample_rows = [
        {"price": 10.0, "quantity": 100.0},
        {"price": 20.0, "quantity": 50.0},
        {"price": 30.0, "quantity": 33.0},
        {"price": 40.0, "quantity": 25.0},
    ]

    with patch.object(agent.schema_service, "get_database_context") as mock_get_ctx, \
         patch.object(agent.sql_generator, "generate_sql", new_callable=AsyncMock) as mock_gen_sql, \
         patch.object(agent.sql_generator, "execute_with_repair", new_callable=AsyncMock) as mock_exec, \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock) as mock_rep, \
         patch("app.core.config.settings.settings.use_llm_understanding", False):

        mock_rep.return_value = ("Sample correlation report", None)
        mock_ctx = MagicMock()
        mock_ctx.schema = {
            "products": {
                "columns": [
                    {"name": "price", "type": "float"},
                    {"name": "quantity", "type": "float"},
                ]
            }
        }
        mock_ctx.catalog = None
        mock_ctx.total_tables = 1
        mock_ctx.total_columns = 2
        mock_get_ctx.return_value = mock_ctx

        mock_gen_sql.return_value = "SELECT price, quantity FROM products"
        mock_exec.return_value = (sample_rows, "SELECT price, quantity FROM products", None, None, [])

        res = await agent.ask("هل هناك علاقة بين السعر والكمية؟", db=mock_db)

        assert res["success"] is True
        assert res["analysis_plan_summary"]["analysis_type"] == "correlation"
        assert res["analysis_result"]["analysis_type"] == "correlation"
        assert len(res["analysis_result"]["findings"]) > 0


def test_insight_engine_incorporates_domain_analytical_findings():
    """Verify InsightEngine elevates domain findings into prioritized insights and prompt context."""
    engine = InsightEngine()
    analytics = AnalyticsResult(
        dataset=DatasetSummary(row_count=4, column_count=2, column_names=["period", "sales"], numeric_columns=["sales"], date_columns=["period"]),
        numeric_stats={},
        categorical_stats={},
        analytical_findings=[
            "Overall growth rate: +100.0% across 4 periods (monthly)",
            "Peak volume observed at 2024-04 with 2,000.00",
        ],
        analysis_type="trend",
        executed_analyzers=["TrendAnalyzer"],
    )

    insight_res = engine.generate_insights(analytics)

    assert len(insight_res.insights) >= 2
    # Verify domain findings are in insights list
    messages = [i.message for i in insight_res.insights]
    assert any("+100.0%" in m for m in messages)
    assert any("Peak" in m for m in messages)

    # Verify findings appear in prompt_context for LLM
    assert "+100.0%" in insight_res.prompt_context
    assert "Peak volume" in insight_res.prompt_context


def test_analysis_result_from_analytics_extracts_computed_metrics():
    """Verify AnalysisResult helper extracts computed_metrics from task_results."""
    analytics = AnalyticsResult(
        dataset=DatasetSummary(row_count=4, column_count=2),
        analytical_findings=["Overall growth rate: +100.0%"],
        task_results=[
            {
                "task_id": "task_calc_growth_rate",
                "name": "Calculate Trajectory & Growth Rate",
                "computed_metrics": {
                    "overall_growth_pct": 100.0,
                    "trend_direction": "upward",
                    "peak_period": "2024-04",
                    "peak_value": 2000.0,
                },
                "findings": ["Overall growth rate: +100.0%"],
            }
        ],
        analysis_type="trend",
        executed_analyzers=["TrendAnalyzer"],
    )

    unified = AnalysisResult.from_analytics_and_insights(
        analytics_result=analytics,
        query_spec=QuerySpec(raw_question="اتجاه المبيعات", analysis_type=AnalysisType.TREND),
    )

    assert unified.analysis_type == "trend"
    assert unified.metrics["overall_growth_pct"] == 100.0
    assert unified.metrics["trend_direction"] == "upward"
    assert unified.metrics["peak_period"] == "2024-04"
    assert "Overall growth rate: +100.0%" in unified.findings
