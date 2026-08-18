"""Base insight generator abstract interface."""
from abc import ABC, abstractmethod
from typing import List
from app.analytics.models import AnalyticsResult, InsightItem


class BaseInsightGenerator(ABC):
    """Abstract base class for all deterministic insight generators."""

    @abstractmethod
    def generate(self, analytics: AnalyticsResult) -> List[InsightItem]:
        """Inspect AnalyticsResult and return a list of prioritized InsightItem objects."""
        pass
