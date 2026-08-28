"""Tests for Trend Analysis Engine."""
import pytest
from app.services.analysis.engines.trend import TrendEngine


def test_trend_engine_monthly_upward():
    rows = [
        {"period": "2024-01-01", "revenue": 100.0},
        {"period": "2024-02-01", "revenue": 120.0},
        {"period": "2024-03-01", "revenue": 150.0},
        {"period": "2024-04-01", "revenue": 200.0},
    ]

    result = TrendEngine.compute_trend(rows, date_col="period", metric_col="revenue")

    assert result["trend_direction"] == "upward"
    assert result["peak"]["value"] == 200.0
    assert result["trough"]["value"] == 100.0
    assert result["overall_growth_pct"] == 100.0
    assert len(result["mom_rates"]) == 3


def test_trend_engine_downward():
    rows = [
        {"period": "2024-01-01", "revenue": 500.0},
        {"period": "2024-02-01", "revenue": 400.0},
        {"period": "2024-03-01", "revenue": 300.0},
    ]

    result = TrendEngine.compute_trend(rows, date_col="period", metric_col="revenue")

    assert result["trend_direction"] == "downward"
    assert result["peak"]["value"] == 500.0
    assert result["trough"]["value"] == 300.0
    assert result["overall_growth_pct"] == -40.0
