from __future__ import annotations
from loguru import logger
from typing import Any, Dict, Optional
from typing import List, Dict, Any
from typing import Tuple
import threading

# --- From metrics.py ---
class MetricsCollector:
    """Collects pipeline success metrics, token usage, and estimates USD cost."""

    # Default pricing per 1,000 tokens (GPT-3.5-Turbo / Fast Tier default)
    PROMPT_COST_PER_1K = 0.0015
    COMPLETION_COST_PER_1K = 0.0020

    def estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Calculate estimated LLM API cost in USD."""
        p_cost = (prompt_tokens / 1000.0) * self.PROMPT_COST_PER_1K
        c_cost = (completion_tokens / 1000.0) * self.COMPLETION_COST_PER_1K
        return round(p_cost + c_cost, 6)

    def build_token_usage(self, prompt_tokens: int = 0, completion_tokens: int = 0) -> TokenUsage:
        """Construct TokenUsage model with estimated cost."""
        total = prompt_tokens + completion_tokens
        cost = self.estimate_cost(prompt_tokens, completion_tokens)
        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            estimated_cost_usd=cost,
        )

    def collect_metrics(self, payload: Dict[str, Any]) -> EvaluationMetrics:
        """Extract pipeline metrics from raw execution payload dict."""
        return EvaluationMetrics(
            sql_generation_success=payload.get("sql_generation_success", True),
            sql_execution_success=payload.get("sql_execution_success", True),
            repair_attempts=payload.get("repair_attempts", 0),
            grounding_validation_success=payload.get("grounding_validation_success", True),
            analytics_success=payload.get("analytics_success", True),
            insight_success=payload.get("insight_success", True),
            report_success=payload.get("report_success", True),
            chart_success=payload.get("chart_success", True),
        )


# --- From scoring.py ---
class EvaluationScorer:
    """Computes confidence_score (0.0 - 1.0) and quality_score (0.0 - 100.0) with strict correctness."""

    def compute_scores(self, metrics: EvaluationMetrics, latency: StageLatency) -> Tuple[float, float]:
        """
        Compute confidence score and quality score for a pipeline run.

        If SQL execution or generation fails, confidence and quality drop strictly
        rather than returning false high scores.

        Returns:
            Tuple[float, float]: (confidence_score, quality_score)
        """
        # 1. Hard failure mode: if SQL generation or execution failed
        if not metrics.sql_execution_success or not metrics.sql_generation_success:
            confidence_score = 0.0
            # If a clean fallback report was delivered without crash, assign small grace score (max 10), else 0
            quality_score = 10.0 if metrics.report_success else 0.0
            return confidence_score, quality_score

        # 2. Confidence Score Calculation (0.0 to 1.0) for successful runs
        conf = 0.40  # Base confidence for successful execution

        if metrics.grounding_validation_success:
            conf += 0.20

        # Penalize repair attempts (0 repairs = +0.20, 1 repair = +0.10, >1 repairs = +0.0)
        if metrics.repair_attempts == 0:
            conf += 0.20
        elif metrics.repair_attempts == 1:
            conf += 0.10

        if metrics.report_success and metrics.analytics_success:
            conf += 0.20

        confidence_score = round(min(max(conf, 0.0), 1.0), 2)

        # 3. Quality Score Calculation (0.0 to 100.0)
        quality = 100.0

        if not metrics.grounding_validation_success:
            quality -= 20.0

        if not metrics.report_success:
            quality -= 20.0

        if not metrics.analytics_success:
            quality -= 10.0

        # Repair attempt penalties (-15 points per repair attempt)
        quality -= (metrics.repair_attempts * 15.0)

        # Latency penalty for very slow queries (> 5 seconds)
        if latency.total_ms > 5000.0:
            quality -= 10.0

        quality_score = round(min(max(quality, 0.0), 100.0), 1)

        return confidence_score, quality_score


# --- From telemetry.py ---
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
