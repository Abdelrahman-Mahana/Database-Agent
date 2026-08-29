from __future__ import annotations
from abc import ABC, abstractmethod
from app.services.analytics.models import AnalyticsResult, InsightItem
from app.services.analytics.models import AnalyticsResult, InsightItem, InsightSeverity
from typing import List


# --- From base.py ---
class BaseInsightGenerator(ABC):
    """Abstract base class for all deterministic insight generators."""

    @abstractmethod
    def generate(self, analytics: AnalyticsResult) -> List[InsightItem]:
        """Inspect AnalyticsResult and return a list of prioritized InsightItem objects."""
        pass









# --- From categorical_insights.py ---
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


# --- From dataset_insights.py ---
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


# --- From numeric_insights.py ---
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
