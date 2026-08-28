"""Deterministic Analytics & Insight Engine package."""
from app.services.analytics.models import (
    AnalyticsResult,
    DatasetSummary,
    NumericSummary,
    CategoricalSummary,
    ValueFrequency,
    InsightSeverity,
    InsightItem,
    InsightResult,
)
from app.services.analytics.engine import AnalyticsEngine
from app.services.analytics.insight_engine import InsightEngine
from app.services.analytics.analyzers.base import BaseAnalyzer
from app.services.analytics.insights.base import BaseInsightGenerator

__all__ = [
    "AnalyticsEngine",
    "AnalyticsResult",
    "DatasetSummary",
    "NumericSummary",
    "CategoricalSummary",
    "ValueFrequency",
    "InsightEngine",
    "InsightResult",
    "InsightItem",
    "InsightSeverity",
    "BaseAnalyzer",
    "BaseInsightGenerator",
]
