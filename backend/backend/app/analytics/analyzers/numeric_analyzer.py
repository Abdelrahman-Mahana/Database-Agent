"""Numeric statistics analyzer."""
import math
import statistics
from typing import Any, List, Dict
from app.analytics.analyzers.base import BaseAnalyzer
from app.analytics.models import DatasetSummary, NumericSummary


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
