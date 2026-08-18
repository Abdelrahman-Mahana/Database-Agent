"""Base analyzer abstract interface."""
from abc import ABC, abstractmethod
from typing import Any, List, Dict
from app.analytics.models import DatasetSummary


class BaseAnalyzer(ABC):
    """Abstract base class for all deterministic analytics analyzers."""

    @abstractmethod
    def analyze(self, rows: List[Dict[str, Any]], dataset_summary: DatasetSummary) -> Any:
        """Process result rows and return specific analytics metric object/dict."""
        pass
