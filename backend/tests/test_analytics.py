"""Unit tests for deterministic AnalyticsEngine."""
import pytest
from app.analytics import AnalyticsEngine, AnalyticsResult, BaseAnalyzer


def test_analytics_engine_empty_input():
    engine = AnalyticsEngine()
    result = engine.analyze([])
    assert isinstance(result, AnalyticsResult)
    assert result.dataset.row_count == 0
    assert result.dataset.column_count == 0
    assert result.numeric_stats == {}
    assert result.categorical_stats == {}


def test_analytics_engine_numeric_and_categorical():
    data = [
        {"name": "Alice", "country": "USA", "age": 30, "salary": 1000.0},
        {"name": "Bob", "country": "USA", "age": 40, "salary": 2000.0},
        {"name": "Charlie", "country": "Canada", "age": 50, "salary": 3000.0},
        {"name": "David", "country": "USA", "age": None, "salary": None},
    ]

    engine = AnalyticsEngine()
    result = engine.analyze(data)

    # Dataset Summary
    assert result.dataset.row_count == 4
    assert result.dataset.column_count == 4
    assert "age" in result.dataset.numeric_columns
    assert "salary" in result.dataset.numeric_columns
    assert "country" in result.dataset.categorical_columns

    # Numeric Stats
    age_stats = result.numeric_stats["age"]
    assert age_stats.count == 4
    assert age_stats.null_count == 1
    assert age_stats.min_value == 30.0
    assert age_stats.max_value == 50.0
    assert age_stats.mean == 40.0
    assert age_stats.median == 40.0

    salary_stats = result.numeric_stats["salary"]
    assert salary_stats.mean == 2000.0

    # Categorical Stats
    country_stats = result.categorical_stats["country"]
    assert country_stats.count == 4
    assert country_stats.null_count == 0
    assert country_stats.distinct_count == 2
    assert len(country_stats.top_values) == 2
    # Top value should be USA (3 occurrences, 75.0%)
    top_country = country_stats.top_values[0]
    assert top_country.value == "USA"
    assert top_country.count == 3
    assert top_country.percentage == 75.0


def test_custom_analyzer_registration():
    class CustomDummyAnalyzer(BaseAnalyzer):
        def __init__(self):
            self.called = False
        def analyze(self, rows, dataset_summary):
            self.called = True
            return {"dummy": True}

    dummy = CustomDummyAnalyzer()
    engine = AnalyticsEngine()
    engine.register_analyzer(dummy)

    data = [{"col1": 10}, {"col1": 20}]
    engine.analyze(data)
    assert dummy.called is True
