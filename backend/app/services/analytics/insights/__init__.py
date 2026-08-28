"""Insights package."""
from app.services.analytics.insights.base import BaseInsightGenerator
from app.services.analytics.insights.dataset_insights import DatasetInsightGenerator
from app.services.analytics.insights.numeric_insights import NumericInsightGenerator
from app.services.analytics.insights.categorical_insights import CategoricalInsightGenerator

__all__ = [
    "BaseInsightGenerator",
    "DatasetInsightGenerator",
    "NumericInsightGenerator",
    "CategoricalInsightGenerator",
]
