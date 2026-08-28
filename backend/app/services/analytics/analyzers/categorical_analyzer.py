"""Categorical distribution and frequency analyzer."""
from collections import Counter
from typing import Any, List, Dict
from app.services.analytics.analyzers.base import BaseAnalyzer
from app.services.analytics.models import DatasetSummary, CategoricalSummary, ValueFrequency


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
