"""Numeric column insight generator."""
from typing import List
from app.services.analytics.models import AnalyticsResult, InsightItem, InsightSeverity
from app.services.analytics.insights.base import BaseInsightGenerator


class NumericInsightGenerator(BaseInsightGenerator):
    """Generates insights for min/max values, mean vs median skew, and low variance columns."""

    def generate(self, analytics: AnalyticsResult) -> List[InsightItem]:
        items: List[InsightItem] = []

        for col, stat in analytics.numeric_stats.items():
            if stat.count == 0 or stat.min_value is None:
                continue

            # 1. Single value / Constant Column Warning
            if stat.distinct_count == 1:
                items.append(
                    InsightItem(
                        category="numeric",
                        severity=InsightSeverity.WARNING,
                        title="Constant Numeric Value",
                        message=f"Column '{col}' has constant value {stat.min_value} across all rows.",
                        importance_score=70,
                    )
                )
                continue

            # 2. Key Range & Averages Insight
            range_str = f"Range: [{stat.min_value} to {stat.max_value}]"
            avg_str = f"Mean: {stat.mean}, Median: {stat.median}"
            items.append(
                InsightItem(
                    category="numeric",
                    severity=InsightSeverity.INFO,
                    title=f"Numeric Summary: {col}",
                    message=f"Column '{col}' — {range_str}, {avg_str}.",
                    importance_score=50,
                )
            )

            # 3. Skew Detection (Mean vs Median disparity relative to stdev)
            if stat.stdev and stat.stdev > 0 and stat.mean is not None and stat.median is not None:
                skew_diff = abs(stat.mean - stat.median)
                if skew_diff / stat.stdev > 0.5:
                    direction = "right-skewed (mean > median)" if stat.mean > stat.median else "left-skewed (mean < median)"
                    items.append(
                        InsightItem(
                            category="numeric",
                            severity=InsightSeverity.INFO,
                            title="Distribution Skew",
                            message=f"Column '{col}' distribution is {direction} (mean {stat.mean} vs median {stat.median}).",
                            importance_score=60,
                        )
                    )

        return items
