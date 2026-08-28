"""Evaluation scorer for computing confidence and quality metrics."""
from typing import Tuple
from app.services.evaluation.models import EvaluationMetrics, StageLatency


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
