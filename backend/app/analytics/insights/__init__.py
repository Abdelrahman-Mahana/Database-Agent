"""Insights package."""
from app.analytics.insights.base import BaseInsightGenerator
from app.analytics.insights.dataset_insights import DatasetInsightGenerator
from app.analytics.insights.numeric_insights import NumericInsightGenerator
from app.analytics.insights.categorical_insights import CategoricalInsightGenerator

__all__ = [
    "BaseInsightGenerator",
    "DatasetInsightGenerator",
    "NumericInsightGenerator",
    "CategoricalInsightGenerator",
]
