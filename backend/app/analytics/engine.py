"""Analytics Engine — orchestrates deterministic analyzers over SQL result sets."""
import time
from typing import Any, List, Dict
from app.analytics.models import AnalyticsResult, DatasetSummary
from app.analytics.analyzers.base import BaseAnalyzer
from app.analytics.analyzers.summary_analyzer import DatasetSummaryAnalyzer
from app.analytics.analyzers.numeric_analyzer import NumericAnalyzer
from app.analytics.analyzers.categorical_analyzer import CategoricalAnalyzer


class AnalyticsEngine:
    """
    Deterministic Analytics Engine.
    Executes modular analyzers over raw SQL query result sets (list[dict])
    and outputs a structured AnalyticsResult object.
    """

    def __init__(self):
        self.summary_analyzer = DatasetSummaryAnalyzer()
        self.numeric_analyzer = NumericAnalyzer()
        self.categorical_analyzer = CategoricalAnalyzer()
        self.custom_analyzers: List[BaseAnalyzer] = []

    def register_analyzer(self, analyzer: BaseAnalyzer) -> None:
        """Register a custom analyzer to extend the analytics engine pipeline."""
        if isinstance(analyzer, BaseAnalyzer):
            self.custom_analyzers.append(analyzer)

    def analyze(self, rows: List[Dict[str, Any]]) -> AnalyticsResult:
        """
        Execute deterministic analytics over query result rows.

        Args:
            rows: SQL query result set formatted as a list of dictionaries.

        Returns:
            AnalyticsResult: Structured object containing dataset, numeric, and categorical metrics.
        """
        start_time = time.time()

        if not rows:
            return AnalyticsResult(
                dataset=DatasetSummary(),
                numeric_stats={},
                categorical_stats={},
                execution_time_ms=0.0,
            )

        # 1. Dataset metadata & column classifications
        dataset_summary = self.summary_analyzer.analyze(rows)

        # 2. Numeric statistics
        numeric_stats = self.numeric_analyzer.analyze(rows, dataset_summary)

        # 3. Categorical distribution statistics
        categorical_stats = self.categorical_analyzer.analyze(rows, dataset_summary)

        # 4. Custom analyzers execution
        for custom_analyzer in self.custom_analyzers:
            try:
                custom_analyzer.analyze(rows, dataset_summary)
            except Exception:
                pass

        execution_time_ms = (time.time() - start_time) * 1000

        return AnalyticsResult(
            dataset=dataset_summary,
            numeric_stats=numeric_stats,
            categorical_stats=categorical_stats,
            execution_time_ms=round(execution_time_ms, 2),
        )
