"""Tests for Correlation Analysis Engine."""
import pytest
from app.services.analysis.engines.correlation import CorrelationEngine


def test_positive_correlation_engine():
    rows = [
        {"price": 10.0, "quantity": 100.0},
        {"price": 20.0, "quantity": 200.0},
        {"price": 30.0, "quantity": 300.0},
        {"price": 40.0, "quantity": 400.0},
    ]

    result = CorrelationEngine.compute_correlation(rows, col_x="price", col_y="quantity")

    assert result["pearson_r"] == pytest.approx(1.0, rel=0.01)
    assert result["direction"] == "positive"
    assert result["strength"] == "very_strong"
    assert any("السببية" in lim or "causation" in lim.lower() for lim in result["limitations"])


def test_negative_correlation_engine():
    rows = [
        {"discount": 0.1, "margin": 0.9},
        {"discount": 0.2, "margin": 0.8},
        {"discount": 0.3, "margin": 0.7},
        {"discount": 0.4, "margin": 0.6},
    ]

    result = CorrelationEngine.compute_correlation(rows, col_x="discount", col_y="margin")

    assert result["pearson_r"] == pytest.approx(-1.0, rel=0.01)
    assert result["direction"] == "negative"
    assert result["strength"] == "very_strong"
