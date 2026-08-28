"""Metrics collector and cost calculator for AI evaluation."""
from typing import Any, Dict, Optional
from app.services.evaluation.models import EvaluationMetrics, TokenUsage


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
