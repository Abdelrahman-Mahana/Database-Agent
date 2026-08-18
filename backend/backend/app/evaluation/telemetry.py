"""Telemetry and structured logging for AI Evaluation results."""
import threading
from typing import List, Dict, Any
from loguru import logger
from app.evaluation.models import EvaluationResult


class EvaluationTelemetry:
    """Logs evaluation results and maintains an in-memory telemetry buffer."""

    _lock = threading.Lock()
    _history_buffer: List[EvaluationResult] = []
    MAX_BUFFER_SIZE = 100

    def record_evaluation(self, result: EvaluationResult) -> None:
        """Log evaluation result and add to in-memory telemetry buffer."""
        logger.bind(
            metric="ai_evaluation",
            request_id=result.request_id,
            confidence_score=result.confidence_score,
            quality_score=result.quality_score,
            execution_success=result.metrics.sql_execution_success,
            total_latency_ms=result.stage_latency.total_ms,
            total_tokens=result.token_usage.total_tokens,
            estimated_cost_usd=result.token_usage.estimated_cost_usd,
        ).info(
            f"AI Evaluation completed: Quality {result.quality_score}/100, "
            f"Confidence {result.confidence_score}, Latency {result.stage_latency.total_ms:.1f}ms."
        )

        with self._lock:
            self._history_buffer.append(result)
            if len(self._history_buffer) > self.MAX_BUFFER_SIZE:
                self._history_buffer.pop(0)

    @classmethod
    def get_history(cls) -> List[EvaluationResult]:
        """Retrieve recorded evaluation history."""
        with cls._lock:
            return list(cls._history_buffer)

    @classmethod
    def clear_history(cls) -> None:
        """Clear recorded telemetry buffer."""
        with cls._lock:
            cls._history_buffer.clear()
