from __future__ import annotations
from abc import ABC, abstractmethod
from app.services.analytics.models import DatasetSummary
from app.services.analytics.models import DatasetSummary, CategoricalSummary, ValueFrequency
from app.services.analytics.models import DatasetSummary, NumericSummary
from collections import Counter
from typing import Any, List, Dict
import math
import re
import statistics


# --- From base.py ---
class BaseAnalyzer(ABC):
    """Abstract base class for all deterministic analytics analyzers."""

    @abstractmethod
    def analyze(self, rows: List[Dict[str, Any]], dataset_summary: DatasetSummary) -> Any:
        """Process result rows and return specific analytics metric object/dict."""
        pass









# --- From categorical_analyzer.py ---
class CategoricalAnalyzer(BaseAnalyzer):
    """Computes top values, bottom values, frequencies, percentages, and distinct counts for categorical columns."""

    def analyze(self, rows: List[Dict[str, Any]], dataset_summary: DatasetSummary) -> Dict[str, CategoricalSummary]:
        """Compute categorical distribution statistics for all non-numeric columns in dataset_summary."""
        results: Dict[str, CategoricalSummary] = {}
        if not rows or not dataset_summary:
            return results

        # Combine categorical and date columns for distribution analysis
        target_columns = dataset_summary.categorical_columns + dataset_summary.date_columns
        if not target_columns:
            return results

        total_rows = len(rows)

        for col in target_columns:
            val_counts: Counter = Counter()
            null_count = 0

            for row in rows:
                val = row.get(col)
                if val is None:
                    null_count += 1
                else:
                    val_counts[str(val)] += 1

            non_null_rows = total_rows - null_count
            distinct_count = len(val_counts)

            if not val_counts or non_null_rows <= 0:
                results[col] = CategoricalSummary(
                    column_name=col,
                    count=total_rows,
                    null_count=null_count,
                    distinct_count=0,
                    top_values=[],
                    bottom_values=[],
                )
                continue

            # Sort by frequency descending for top values, ascending for bottom values
            sorted_items = val_counts.most_common()
            
            top_items = sorted_items[:min(5, len(sorted_items))]
            bottom_items = sorted_items[-min(5, len(sorted_items)):]
            bottom_items.reverse()  # lowest first

            top_freqs = [
                ValueFrequency(
                    value=v,
                    count=cnt,
                    percentage=round((cnt / non_null_rows) * 100, 2),
                )
                for v, cnt in top_items
            ]

            bottom_freqs = [
                ValueFrequency(
                    value=v,
                    count=cnt,
                    percentage=round((cnt / non_null_rows) * 100, 2),
                )
                for v, cnt in bottom_items
            ]

            results[col] = CategoricalSummary(
                column_name=col,
                count=total_rows,
                null_count=null_count,
                distinct_count=distinct_count,
                top_values=top_freqs,
                bottom_values=bottom_freqs,
            )

        return results


# --- From numeric_analyzer.py ---
class NumericAnalyzer(BaseAnalyzer):
    """Computes min, max, mean, median, stdev, null counts, and distinct counts for numeric columns."""

    def analyze(self, rows: List[Dict[str, Any]], dataset_summary: DatasetSummary) -> Dict[str, NumericSummary]:
        """Compute numeric statistics for all numeric columns in dataset_summary."""
        results: Dict[str, NumericSummary] = {}
        if not rows or not dataset_summary or not dataset_summary.numeric_columns:
            return results

        total_rows = len(rows)

        for col in dataset_summary.numeric_columns:
            values: List[float] = []
            null_count = 0

            for row in rows:
                val = row.get(col)
                if val is None:
                    null_count += 1
                    continue
                try:
                    f_val = float(val)
                    if not math.isnan(f_val):
                        values.append(f_val)
                    else:
                        null_count += 1
                except (ValueError, TypeError):
                    null_count += 1

            if not values:
                results[col] = NumericSummary(
                    column_name=col,
                    count=total_rows,
                    null_count=null_count,
                    distinct_count=0,
                )
                continue

            distinct_count = len(set(values))
            min_val = min(values)
            max_val = max(values)
            mean_val = statistics.mean(values)
            median_val = statistics.median(values)
            stdev_val = statistics.stdev(values) if len(values) > 1 else 0.0

            results[col] = NumericSummary(
                column_name=col,
                count=total_rows,
                null_count=null_count,
                distinct_count=distinct_count,
                min_value=round(min_val, 4),
                max_value=round(max_val, 4),
                mean=round(mean_val, 4),
                median=round(median_val, 4),
                stdev=round(stdev_val, 4),
            )

        return results


# --- From summary_analyzer.py ---
class DatasetSummaryAnalyzer(BaseAnalyzer):
    """Analyzes table dimensions and classifies columns into numeric, categorical, or temporal."""

    def analyze(self, rows: List[Dict[str, Any]], dataset_summary: DatasetSummary = None) -> DatasetSummary:
        """Inspect rows and return DatasetSummary metadata."""
        if not rows:
            return DatasetSummary()

        row_count = len(rows)
        columns = list(rows[0].keys())
        column_count = len(columns)

        numeric_cols = []
        categorical_cols = []
        date_cols = []

        sample_rows = rows[:min(50, row_count)]

        for col in columns:
            col_lower = col.lower()
            
            # Check for temporal / date columns first
            temporal_keywords = ("date", "year", "month", "day", "time", "created_at", "updated_at", "period", "quarter", "week", "timestamp", "datetime", "yr", "mo", "qtr")
            if any(term in col_lower for term in temporal_keywords):
                date_cols.append(col)
                continue

            # Check if sample non-null values look like date/period strings (YYYY-MM, YYYY-MM-DD, etc.)
            sample_values = [str(r.get(col, "")).strip() for r in sample_rows if r.get(col) is not None]
            if sample_values and any(re.match(r"^\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?", v) or re.match(r"^\d{4}-W\d{2}", v, re.I) or re.match(r"^\d{4}-Q\d", v, re.I) for v in sample_values[:5]):
                date_cols.append(col)
                continue

            # Sample values to detect numeric vs categorical
            is_numeric = True
            has_non_null = False

            for row in sample_rows:
                val = row.get(col)
                if val is None:
                    continue
                has_non_null = True

                if isinstance(val, (int, float)) and not isinstance(val, bool):
                    continue

                # Try numeric conversion for string numbers
                try:
                    float(str(val))
                except (ValueError, TypeError):
                    is_numeric = False
                    break

            if has_non_null and is_numeric:
                numeric_cols.append(col)
            else:
                categorical_cols.append(col)

        return DatasetSummary(
            row_count=row_count,
            column_count=column_count,
            column_names=columns,
            numeric_columns=numeric_cols,
            categorical_columns=categorical_cols,
            date_columns=date_cols,
        )
