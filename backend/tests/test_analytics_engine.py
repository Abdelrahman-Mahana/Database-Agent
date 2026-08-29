"""Unit tests for the targeted and plan-driven AnalyticsEngine."""
import pytest
from app.services.analytics.engine import AnalyticsEngine
from app.services.analytics.models import AnalyticsResult
from app.services.analysis.registry import AnalysisStrategyRegistry
from app.agent.semantic.models import AnalysisOperation, QuerySpec
from app.agent.semantic.query_spec_builder import QuerySpecBuilder
from app.utils.helpers import AnalysisType


def test_analytics_engine_default_profiling():
    engine = AnalyticsEngine()
    rows = [
        {"id": 1, "country": "Egypt", "sales": 100.0},
        {"id": 2, "country": "Saudi Arabia", "sales": 250.0},
        {"id": 3, "country": "Egypt", "sales": 150.0},
    ]

    res = engine.analyze(rows)
    assert isinstance(res, AnalyticsResult)
    assert res.dataset.row_count == 3
    assert "NumericAnalyzer" in res.executed_analyzers
    assert "CategoricalAnalyzer" in res.executed_analyzers
    assert "sales" in res.numeric_stats
    assert "country" in res.categorical_stats


def test_analytics_engine_correlation_targeted():
    engine = AnalyticsEngine()
    builder = QuerySpecBuilder()
    spec = builder.build_spec("هل فيه علاقة بين السعر والكمية؟")
    plan = AnalysisStrategyRegistry.build_plan_for_spec(spec)

    rows = [
        {"price": 10.0, "quantity": 100.0},
        {"price": 20.0, "quantity": 50.0},
        {"price": 30.0, "quantity": 33.0},
        {"price": 40.0, "quantity": 25.0},
        {"price": 50.0, "quantity": 20.0},
    ]

    res = engine.analyze(rows=rows, analysis_plan=plan)
    assert isinstance(res, AnalyticsResult)
    assert "CorrelationAnalyzer" in res.executed_analyzers
    # Should NOT waste time running CategoricalAnalyzer when not relevant
    assert "CategoricalAnalyzer" not in res.executed_analyzers
    assert len(res.analytical_findings) > 0
    assert any("Correlation" in f for f in res.analytical_findings)


def test_analytics_engine_anomaly_detection_targeted():
    engine = AnalyticsEngine()
    builder = QuerySpecBuilder()
    spec = builder.build_spec("هل فيه قيم شاذة في الأسعار؟")
    plan = AnalysisStrategyRegistry.build_plan_for_spec(spec)

    rows = [
        {"item": "A", "price": 10.0},
        {"item": "B", "price": 12.0},
        {"item": "C", "price": 11.0},
        {"item": "D", "price": 500.0},  # Huge anomaly
        {"item": "E", "price": 13.0},
    ]

    res = engine.analyze(rows=rows, analysis_plan=plan)
    assert "AnomalyAnalyzer" in res.executed_analyzers
    assert len(res.analytical_findings) > 0
    assert any("anomal" in f.lower() or "outlier" in f.lower() or "flagged" in f.lower() for f in res.analytical_findings)


def test_analytics_engine_exploratory_targeted():
    engine = AnalyticsEngine()
    builder = QuerySpecBuilder()
    spec = builder.build_spec("حلل المبيعات")
    plan = AnalysisStrategyRegistry.build_plan_for_spec(spec)

    rows = [
        {"period": "2024-01", "sales": 1000.0},
        {"period": "2024-02", "sales": 1200.0},
        {"period": "2024-03", "sales": 1100.0},
        {"period": "2024-04", "sales": 4000.0},
    ]

    res = engine.analyze(rows=rows, analysis_plan=plan)
    assert len(res.analytical_findings) > 0
    assert len(res.task_results) >= 3
    assert res.analysis_type == "exploratory_analysis"
