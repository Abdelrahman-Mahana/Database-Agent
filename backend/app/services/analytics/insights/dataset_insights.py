"""Dataset-level insight generator."""
from typing import List
from app.services.analytics.models import AnalyticsResult, InsightItem, InsightSeverity
from app.services.analytics.insights.base import BaseInsightGenerator


class DatasetInsightGenerator(BaseInsightGenerator):
    """Generates insights for empty datasets, dataset dimensions, and overall missing data warnings."""

    def generate(self, analytics: AnalyticsResult) -> List[InsightItem]:
        items: List[InsightItem] = []
        ds = analytics.dataset

        # 1. Empty Dataset Detection
        if ds.row_count == 0:
            items.append(
                InsightItem(
                    category="dataset",
                    severity=InsightSeverity.CRITICAL,
                    title="Empty Result Set",
                    message="Query returned 0 rows. No data matches the specified filters.",
                    importance_score=100,
                )
            )
            return items

        # 2. Overview Dimension Insight
        items.append(
            InsightItem(
                category="dataset",
                severity=InsightSeverity.INFO,
                title="Dataset Size",
                message=f"Dataset contains {ds.row_count:,} rows and {ds.column_count} columns.",
                importance_score=40,
            )
        )

        # 3. Column-level Missing Data Warnings
        all_stats = list(analytics.numeric_stats.values()) + list(analytics.categorical_stats.values())
        for col_stat in all_stats:
            if col_stat.null_count > 0:
                missing_pct = round((col_stat.null_count / ds.row_count) * 100, 1)
                if missing_pct >= 50.0:
                    items.append(
                        InsightItem(
                            category="dataset",
                            severity=InsightSeverity.CRITICAL,
                            title="Severe Missing Data",
                            message=f"Column '{col_stat.column_name}' has {missing_pct}% missing values ({col_stat.null_count}/{ds.row_count} rows).",
                            importance_score=90,
                        )
                    )
                elif missing_pct >= 10.0:
                    items.append(
                        InsightItem(
                            category="dataset",
                            severity=InsightSeverity.WARNING,
                            title="Missing Data Warning",
                            message=f"Column '{col_stat.column_name}' has {missing_pct}% missing values ({col_stat.null_count}/{ds.row_count} rows).",
                            importance_score=75,
                        )
                    )

        return items
