"""Unit and integration tests verifying truthful evaluation metrics and preventing false 100/100 and 1.0 confidence on failures."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.evaluation.evaluator import AgentEvaluator
from app.services.evaluation.models import EvaluationMetrics, StageLatency
from app.services.evaluation.scoring import EvaluationScorer
from app.agent.orchestration.analyst_agent import AnalystAgent


def test_evaluation_scorer_zeroes_confidence_on_sql_execution_failure():
    """Verify EvaluationScorer returns 0.0 confidence and low quality score on SQL execution failure."""
    scorer = EvaluationScorer()
    metrics = EvaluationMetrics(
        sql_generation_success=True,
        sql_execution_success=False,
        repair_attempts=1,
        grounding_validation_success=True,
        analytics_success=False,
        insight_success=False,
        report_success=True,  # fallback error report
        chart_success=False,
    )
    latency = StageLatency(total_ms=1200.0)

    confidence, quality = scorer.compute_scores(metrics, latency)

    assert confidence == 0.0
    assert quality <= 10.0


def test_evaluation_scorer_zeroes_confidence_on_sql_generation_failure():
    """Verify EvaluationScorer returns 0.0 confidence on SQL generation failure."""
    scorer = EvaluationScorer()
    metrics = EvaluationMetrics(
        sql_generation_success=False,
        sql_execution_success=False,
        repair_attempts=0,
        grounding_validation_success=False,
        analytics_success=False,
        insight_success=False,
        report_success=False,
        chart_success=False,
    )
    latency = StageLatency(total_ms=500.0)

    confidence, quality = scorer.compute_scores(metrics, latency)

    assert confidence == 0.0
    assert quality == 0.0


def test_evaluation_scorer_rewards_clean_successful_pipeline():
    """Verify EvaluationScorer returns high confidence (>=0.9) and high quality (100) on clean execution."""
    scorer = EvaluationScorer()
    metrics = EvaluationMetrics(
        sql_generation_success=True,
        sql_execution_success=True,
        repair_attempts=0,
        grounding_validation_success=True,
        analytics_success=True,
        insight_success=True,
        report_success=True,
        chart_success=True,
    )
    latency = StageLatency(total_ms=800.0)

    confidence, quality = scorer.compute_scores(metrics, latency)

    assert confidence >= 0.95
    assert quality == 100.0


def test_evaluation_scorer_penalizes_repair_attempts():
    """Verify EvaluationScorer penalizes quality and confidence when repair attempts were required."""
    scorer = EvaluationScorer()
    metrics = EvaluationMetrics(
        sql_generation_success=True,
        sql_execution_success=True,
        repair_attempts=1,
        grounding_validation_success=True,
        analytics_success=True,
        insight_success=True,
        report_success=True,
        chart_success=True,
    )
    latency = StageLatency(total_ms=1500.0)

    confidence, quality = scorer.compute_scores(metrics, latency)

    assert confidence < 1.0
    assert quality == 85.0


@pytest.mark.asyncio
async def test_analyst_agent_evaluation_trace_collapses_confidence_on_execution_error():
    """Verify AnalystAgent / LangGraph sets confidence to 0.0 on unrecoverable SQL error."""
    agent = AnalystAgent()
    mock_db = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.schema = {"invoices": {"columns": [{"name": "total", "type": "float"}]}}
    mock_ctx.catalog = None
    mock_ctx.total_tables = 1
    mock_ctx.total_columns = 1

    with patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.sql_generator, "generate_sql", new_callable=AsyncMock) as mock_gen_sql, \
         patch.object(agent.sql_generator, "execute_with_repair", new_callable=AsyncMock) as mock_exec:

        mock_gen_sql.return_value = "SELECT sum(total) FROM invoices"
        # Simulate unrecoverable execution failure
        mock_exec.return_value = (None, "SELECT sum(total) FROM invoices", "Fatal SQLite error: disk I/O error", "execution_error", [])

        res = await agent.ask("What is the total revenue?", db=mock_db)

    assert res["success"] is False or res.get("error") is not None
    assert res.get("confidence_breakdown", {}).get("overall") == 0.0
    assert res.get("evaluation_trace", {}).get("confidence") == 0.0
    assert res.get("confidence_breakdown", {}).get("sql") == 0.0
    assert res.get("confidence_breakdown", {}).get("execution") == 0.0
