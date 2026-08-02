"""Categorical column insight generator."""
from typing import List
from app.analytics.models import AnalyticsResult, InsightItem, InsightSeverity
from app.analytics.insights.base import BaseInsightGenerator


class CategoricalInsightGenerator(BaseInsightGenerator):
    """Generates insights for dominant values, high cardinality, and single value categorical columns."""

    def generate(self, analytics: AnalyticsResult) -> List[InsightItem]:
        items: List[InsightItem] = []
        total_rows = analytics.dataset.row_count

        for col, stat in analytics.categorical_stats.items():
            if stat.count == 0 or not stat.top_values:
                continue

            # 1. Single Value Column Warning
            if stat.distinct_count == 1:
                items.append(
                    InsightItem(
                        category="categorical",
                        severity=InsightSeverity.WARNING,
                        title="Constant Categorical Value",
                        message=f"Column '{col}' has single value '{stat.top_values[0].value}' across all rows.",
                        importance_score=70,
                    )
                )
                continue

            # 2. High Cardinality Warning
            if total_rows > 5 and (stat.distinct_count / total_rows) > 0.8:
                items.append(
                    InsightItem(
                        category="categorical",
                        severity=InsightSeverity.WARNING,
                        title="High Cardinality",
                        message=f"Column '{col}' has high cardinality ({stat.distinct_count} distinct values out of {total_rows} rows).",
                        importance_score=65,
                    )
                )

            # 3. Dominant Category Detection
            top_val = stat.top_values[0]
            if top_val.percentage >= 50.0:
                items.append(
                    InsightItem(
                        category="categorical",
                        severity=InsightSeverity.INFO,
                        title="Dominant Category",
                        message=f"Category '{top_val.value}' dominates '{col}' accounting for {top_val.percentage}% of rows ({top_val.count}/{total_rows}).",
                        importance_score=80,
                    )
                )
            else:
                items.append(
                    InsightItem(
                        category="categorical",
                        severity=InsightSeverity.INFO,
                        title=f"Top Category: {col}",
                        message=f"Most frequent value in '{col}' is '{top_val.value}' ({top_val.percentage}%).",
                        importance_score=45,
                    )
                )

        return items
