"""Insight Engine — transforms AnalyticsResult into compact, prioritized semantic insights."""
from typing import List
from app.services.analytics.models import AnalyticsResult, InsightResult, InsightItem, InsightSeverity
from app.services.analytics.insights.base import BaseInsightGenerator
from app.services.analytics.insights.dataset_insights import DatasetInsightGenerator
from app.services.analytics.insights.numeric_insights import NumericInsightGenerator
from app.services.analytics.insights.categorical_insights import CategoricalInsightGenerator


class InsightEngine:
    """
    Deterministic Insight Engine.
    Transforms raw AnalyticsResult statistical models into a compact, prioritized
    semantic InsightResult representation optimized for LLM prompt consumption.
    """

    def __init__(self):
        self.generators: List[BaseInsightGenerator] = [
            DatasetInsightGenerator(),
            NumericInsightGenerator(),
            CategoricalInsightGenerator(),
        ]

    def register_generator(self, generator: BaseInsightGenerator) -> None:
        """Register a custom insight generator to extend the engine."""
        if isinstance(generator, BaseInsightGenerator):
            self.generators.append(generator)

    def generate_insights(self, analytics: AnalyticsResult) -> InsightResult:
        """
        Generate prioritized semantic insights from AnalyticsResult.

        Args:
            analytics: Statistical AnalyticsResult object from AnalyticsEngine.

        Returns:
            InsightResult: Compact, prioritized semantic insight structure.
        """
        raw_items: List[InsightItem] = []

        # 1. Execute all insight generators
        for gen in self.generators:
            try:
                items = gen.generate(analytics)
                raw_items.extend(items)
            except Exception:
                pass

        # 1.1 Include domain-specific analytical findings (Trend, Anomaly, Correlation, etc.)
        if analytics and hasattr(analytics, "analytical_findings") and analytics.analytical_findings:
            for idx, finding in enumerate(analytics.analytical_findings):
                if finding and isinstance(finding, str):
                    raw_items.append(
                        InsightItem(
                            category="domain_analysis",
                            severity=InsightSeverity.INFO,
                            title="Analytical Finding",
                            message=finding,
                            importance_score=max(70, int(95 - (idx * 2))),
                        )
                    )

        # 2. Prioritize and sort by importance_score descending
        sorted_items = sorted(raw_items, key=lambda x: x.importance_score, reverse=True)

        # 3. Extract critical warnings
        critical_warnings = [
            item.message for item in sorted_items
            if item.severity in (InsightSeverity.CRITICAL, InsightSeverity.WARNING)
        ]

        # 4. Generate one-line summary
        ds = analytics.dataset
        summary = f"Result set contains {ds.row_count:,} rows and {ds.column_count} columns."

        # 5. Build compact, token-efficient prompt context text for LLM injection
        prompt_lines = [f"Analytics Summary: {summary}"]
        if critical_warnings:
            prompt_lines.append("Data Warnings:")
            for warn in critical_warnings:
                prompt_lines.append(f"  - {warn}")

        prompt_lines.append("Key Insights:")
        for item in sorted_items:
            if item.severity == InsightSeverity.INFO:
                prompt_lines.append(f"  - {item.message}")

        prompt_context = "\n".join(prompt_lines)

        return InsightResult(
            summary=summary,
            insights=sorted_items,
            critical_warnings=critical_warnings,
            prompt_context=prompt_context,
        )
