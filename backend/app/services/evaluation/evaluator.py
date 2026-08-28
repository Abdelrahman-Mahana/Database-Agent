"""Agent Evaluator — main orchestrator for AI Evaluation Framework."""
from typing import Any, Dict, Optional
from app.services.evaluation.models import EvaluationResult, StageLatency
from app.services.evaluation.metrics import MetricsCollector
from app.services.evaluation.scoring import EvaluationScorer
from app.services.evaluation.telemetry import EvaluationTelemetry


class AgentEvaluator:
    """Orchestrates comprehensive evaluation of completed agent requests."""

    def __init__(self):
        self.metrics_collector = MetricsCollector()
        self.scorer = EvaluationScorer()
        self.telemetry = EvaluationTelemetry()

    def evaluate(
        self,
        question: str,
        sql_query: str,
        execution_payload: Dict[str, Any],
        stage_latency: Optional[StageLatency] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> EvaluationResult:
        """
        Evaluate a completed request and produce a structured EvaluationResult object.

        Args:
            question: User's natural language question.
            sql_query: Generated SQL query string.
            execution_payload: Dict containing success flags and repair attempt counts.
            stage_latency: StageLatency object with execution timings.
            prompt_tokens: Prompt tokens used.
            completion_tokens: Completion tokens used.

        Returns:
            EvaluationResult: Structured evaluation object.
        """
        metrics = self.metrics_collector.collect_metrics(execution_payload)
        token_usage = self.metrics_collector.build_token_usage(prompt_tokens, completion_tokens)
        latency = stage_latency or StageLatency()

        confidence_score, quality_score = self.scorer.compute_scores(metrics, latency)

        summary = (
            f"Execution {'succeeded' if metrics.sql_execution_success else 'failed'} "
            f"with quality score {quality_score}/100 and confidence {confidence_score}."
        )

        result = EvaluationResult(
            question=question,
            sql_query=sql_query,
            metrics=metrics,
            stage_latency=latency,
            token_usage=token_usage,
            confidence_score=confidence_score,
            quality_score=quality_score,
            summary=summary,
        )

        self.telemetry.record_evaluation(result)
        return result
