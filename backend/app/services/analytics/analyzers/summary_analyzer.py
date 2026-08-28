"""Dataset summary analyzer for structural metadata and column classification."""
import re
from typing import Any, List, Dict
from app.services.analytics.analyzers.base import BaseAnalyzer
from app.services.analytics.models import DatasetSummary


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
