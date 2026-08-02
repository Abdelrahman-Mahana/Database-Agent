"""Unit tests for AI Evaluation Framework."""
import pytest
from app.evaluation import (
    AgentEvaluator,
    EvaluationResult,
    StageLatency,
    MetricsCollector,
    EvaluationTelemetry,
)


def test_metrics_collector_cost_estimation():
    collector = MetricsCollector()
    cost = collector.estimate_cost(prompt_tokens=1000, completion_tokens=500)
    assert cost > 0.0
    assert cost == 0.0025  # (1*0.0015) + (0.5*0.002)


def test_agent_evaluator_success():
    evaluator = AgentEvaluator()
    EvaluationTelemetry.clear_history()

    payload = {
        "sql_generation_success": True,
        "sql_execution_success": True,
        "repair_attempts": 0,
        "grounding_validation_success": True,
        "analytics_success": True,
        "insight_success": True,
        "report_success": True,
        "chart_success": True,
    }
    latency = StageLatency(total_ms=450.0)

    res = evaluator.evaluate(
        question="Show artists",
        sql_query="SELECT * FROM Artist;",
        execution_payload=payload,
        stage_latency=latency,
        prompt_tokens=500,
        completion_tokens=100,
    )

    assert isinstance(res, EvaluationResult)
    assert res.quality_score == 100.0
    assert res.confidence_score == 1.0
    assert res.token_usage.total_tokens == 600

    history = EvaluationTelemetry.get_history()
    assert len(history) >= 1
    assert history[-1].request_id == res.request_id


def test_agent_evaluator_failure_penalties():
    evaluator = AgentEvaluator()

    payload = {
        "sql_generation_success": True,
        "sql_execution_success": False,
        "repair_attempts": 2,
        "grounding_validation_success": False,
        "analytics_success": False,
        "insight_success": False,
        "report_success": False,
        "chart_success": False,
    }
    latency = StageLatency(total_ms=6000.0)

    res = evaluator.evaluate(
        question="Invalid query",
        sql_query="SELECT * FROM UnknownTable;",
        execution_payload=payload,
        stage_latency=latency,
    )

    assert res.quality_score < 50.0
    assert res.confidence_score < 0.5
