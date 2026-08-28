"""Analytical Engines package: deterministic mathematical, statistical, and forecasting algorithms."""
from app.services.analysis.engines.aggregation_comparison import AggregationComparisonEngine
from app.services.analysis.engines.trend import TrendEngine
from app.services.analysis.engines.distribution import DistributionEngine
from app.services.analysis.engines.anomaly_detection import AnomalyDetectionEngine
from app.services.analysis.engines.correlation import CorrelationEngine
from app.services.analysis.engines.root_cause import RootCauseEngine
from app.services.analysis.engines.data_quality import DataQualityEngine
from app.services.analysis.engines.forecasting import ForecastingEngine
from app.services.analysis.engines.statistical_testing import StatisticalTestingEngine

__all__ = [
    "AggregationComparisonEngine",
    "TrendEngine",
    "DistributionEngine",
    "AnomalyDetectionEngine",
    "CorrelationEngine",
    "RootCauseEngine",
    "DataQualityEngine",
    "ForecastingEngine",
    "StatisticalTestingEngine",
]
