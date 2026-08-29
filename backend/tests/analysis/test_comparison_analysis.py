"""Tests for Comparison and Aggregation Analysis Engine."""
import pytest
from app.services.analysis.engines import AggregationComparisonEngine


def test_comparison_between_entities():
    rows = [
        {"city": "Cairo", "sales": 500000.0},
        {"city": "Alexandria", "sales": 300000.0},
    ]

    comp_res = AggregationComparisonEngine.compute_comparison(rows, group_col="city", metric_col="sales")

    assert comp_res["total_sum"] == 800000.0
    assert comp_res["highest_group"]["group"] == "Cairo"
    assert comp_res["lowest_group"]["group"] == "Alexandria"
    assert abs(comp_res["comparisons"][0]["difference"]) == 200000.0


def test_aggregation_stats():
    rows = [
        {"val": 10.0},
        {"val": 20.0},
        {"val": 30.0},
        {"val": 40.0},
    ]

    res = AggregationComparisonEngine.compute_aggregations(rows, numeric_cols=["val"])
    stats = res["columns"]["val"]

    assert stats["sum"] == 100.0
    assert stats["average"] == 25.0
    assert stats["min"] == 10.0
    assert stats["max"] == 40.0
    assert stats["count"] == 4
