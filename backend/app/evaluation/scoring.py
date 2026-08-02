"""Evaluation scorer for computing confidence and quality metrics."""
from typing import Tuple
from app.evaluation.models import EvaluationMetrics, StageLatency


class EvaluationScorer:
    """Computes confidence_score (0.0 - 1.0) and quality_score (0.0 - 100.0)."""

    def compute_scores(self, metrics: EvaluationMetrics, latency: StageLatency) -> Tuple[float, float]:
        """
        Compute confidence score and quality score for a pipeline run.

        Returns:
            Tuple[float, float]: (confidence_score, quality_score)
        """
        # 1. Confidence Score Calculation (0.0 to 1.0)
        conf = 0.0
        if metrics.sql_execution_success:
            conf += 0.40
        if metrics.grounding_validation_success:
            conf += 0.20
        if metrics.repair_attempts == 0:
            conf += 0.20
        if metrics.report_success and metrics.analytics_success:
            conf += 0.20

        confidence_score = round(min(max(conf, 0.0), 1.0), 2)

        # 2. Quality Score Calculation (0.0 to 100.0)
        quality = 100.0

        if not metrics.sql_execution_success:
            quality -= 40.0

        if not metrics.grounding_validation_success:
            quality -= 15.0

        if not metrics.report_success:
            quality -= 15.0

        if not metrics.analytics_success:
            quality -= 10.0

        # Repair attempt penalties
        quality -= (metrics.repair_attempts * 10.0)

        # Latency penalty for very slow queries (> 5 seconds)
        if latency.total_ms > 5000.0:
            quality -= 10.0

        quality_score = round(min(max(quality, 0.0), 100.0), 1)

        return confidence_score, quality_score
