"""Unit tests for deterministic InsightEngine."""
import pytest
from app.analytics import AnalyticsEngine, InsightEngine, InsightResult, InsightSeverity


def test_insight_engine_empty_dataset():
    analytics_engine = AnalyticsEngine()
    insight_engine = InsightEngine()

    analytics = analytics_engine.analyze([])
    insights = insight_engine.generate_insights(analytics)

    assert isinstance(insights, InsightResult)
    assert len(insights.insights) == 1
    assert insights.insights[0].severity == InsightSeverity.CRITICAL
    assert "0 rows" in insights.insights[0].message
    assert "Critical" in insights.prompt_context or "Empty Result Set" in insights.prompt_context


def test_insight_engine_dataset_insights():
    data = [
        {"name": "Alice", "status": "Active", "score": 90.0},
        {"name": "Bob", "status": "Active", "score": 95.0},
        {"name": "Charlie", "status": "Active", "score": 10.0}, # Skews min
        {"name": "David", "status": "Inactive", "score": None},
    ]

    analytics_engine = AnalyticsEngine()
    insight_engine = InsightEngine()

    analytics = analytics_engine.analyze(data)
    result = insight_engine.generate_insights(analytics)

    assert len(result.insights) > 0
    assert "4 rows and 3 columns" in result.summary

    # Check warning extraction
    assert len(result.critical_warnings) >= 1  # Missing data for score (25%)
    assert any("score" in warn for warn in result.critical_warnings)

    # Check prompt context string generation
    assert "Analytics Summary" in result.prompt_context
    assert "Key Insights" in result.prompt_context
