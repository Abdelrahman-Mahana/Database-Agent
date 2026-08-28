"""Unit tests for the first 4 Analytical Engines:
1. Aggregation / Comparison (average, sum, count, min, max, percentage, difference, growth)
2. Trend (monthly, weekly, daily, YoY, MoM, growth rate)
3. Distribution (mean, median, percentiles, frequency, histogram buckets)
4. Anomaly Detection (IQR, Z-score, percentage deviation)
"""
import pytest
from app.services.analysis.engines import (
    AggregationComparisonEngine,
    TrendEngine,
    DistributionEngine,
    AnomalyDetectionEngine,
)


# ─── 7.1 AGGREGATION & COMPARISON ENGINE TESTS ───


def test_aggregation_engine_metrics():
    rows = [
        {"item": "A", "price": 10.0, "quantity": 5},
        {"item": "B", "price": 20.0, "quantity": 10},
        {"item": "C", "price": 30.0, "quantity": 15},
    ]

    res = AggregationComparisonEngine.compute_aggregations(rows, numeric_cols=["price", "quantity"])
    assert res["row_count"] == 3
    
    price_stats = res["columns"]["price"]
    assert price_stats["sum"] == 60.0
    assert price_stats["average"] == 20.0
    assert price_stats["count"] == 3
    assert price_stats["min"] == 10.0
    assert price_stats["max"] == 30.0

    qty_stats = res["columns"]["quantity"]
    assert qty_stats["sum"] == 30.0
    assert qty_stats["average"] == 10.0


def test_comparison_engine_metrics():
    rows = [
        {"year": "2024", "sales": 1000.0},
        {"year": "2025", "sales": 1500.0},
    ]

    comp_res = AggregationComparisonEngine.compute_comparison(rows, group_col="year", metric_col="sales")
    assert comp_res["total_sum"] == 2500.0
    assert comp_res["highest_group"]["group"] == "2025"
    assert comp_res["lowest_group"]["group"] == "2024"
    
    # Check percentage shares
    assert comp_res["groups"][0]["percentage_share"] == 40.0
    assert comp_res["groups"][1]["percentage_share"] == 60.0

    # Check difference and percentage growth
    comp = comp_res["comparisons"][0]
    assert comp["difference"] == 500.0
    assert comp["growth_pct"] == 50.0

    findings = AggregationComparisonEngine.generate_findings(comp_res)
    assert len(findings) >= 2


# ─── 7.2 TREND ENGINE TESTS ───


def test_trend_engine_mom_and_granularity():
    # Monthly series
    monthly_rows = [
        {"month": "2024-01", "sales": 100.0},
        {"month": "2024-02", "sales": 120.0},
        {"month": "2024-03", "sales": 150.0},
        {"month": "2024-04", "sales": 135.0},
    ]

    trend_res = TrendEngine.compute_trend(monthly_rows, date_col="month", metric_col="sales")
    assert trend_res["granularity"] == "monthly"
    assert trend_res["first_period"] == "2024-01"
    assert trend_res["last_period"] == "2024-04"
    assert trend_res["overall_growth_pct"] == 35.0  # (135 - 100) / 100 * 100
    assert trend_res["peak"]["period"] == "2024-03"
    assert trend_res["trough"]["period"] == "2024-01"
    assert trend_res["trend_direction"] == "upward"
    
    # MoM calculations
    assert len(trend_res["mom_rates"]) == 3
    assert trend_res["mom_rates"][0]["growth_pct"] == 20.0  # Jan to Feb: +20%
    assert trend_res["mom_rates"][1]["growth_pct"] == 25.0  # Feb to Mar: +25%


def test_trend_engine_yoy():
    # Multi-year monthly series for YoY
    yoy_rows = [
        {"month": "2024-01", "sales": 1000.0},
        {"month": "2024-02", "sales": 1200.0},
        {"month": "2025-01", "sales": 1300.0},  # YoY +30% vs 2024-01
        {"month": "2025-02", "sales": 1500.0},  # YoY +25% vs 2024-02
    ]

    trend_res = TrendEngine.compute_trend(yoy_rows, date_col="month", metric_col="sales")
    assert len(trend_res["yoy_rates"]) == 2
    assert trend_res["yoy_rates"][0]["period"] == "2025-01"
    assert trend_res["yoy_rates"][0]["comparison_period"] == "2024-01"
    assert trend_res["yoy_rates"][0]["yoy_growth_pct"] == 30.0


# ─── 7.3 DISTRIBUTION ENGINE TESTS ───


def test_distribution_engine_percentiles_and_buckets():
    data = [{"score": v} for v in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]]

    dist = DistributionEngine.compute_numeric_distribution(data, numeric_col="score", num_buckets=5)
    assert dist["count"] == 10
    assert dist["mean"] == 55.0
    assert dist["median"] == 55.0
    assert dist["min"] == 10.0
    assert dist["max"] == 100.0
    
    # Check percentiles
    p = dist["percentiles"]
    assert p["p50"] == 55.0
    assert p["p25"] < p["p50"] < p["p75"]
    assert dist["iqr"] == round(p["p75"] - p["p25"], 2)

    # Check histogram buckets
    assert len(dist["buckets"]) == 5
    total_bucket_count = sum(b["count"] for b in dist["buckets"])
    assert total_bucket_count == 10


def test_distribution_engine_categorical_frequency():
    data = [
        {"city": "Cairo"},
        {"city": "Cairo"},
        {"city": "Alexandria"},
        {"city": "Giza"},
        {"city": "Cairo"},
    ]

    freq = DistributionEngine.compute_categorical_frequency(data, categorical_col="city")
    assert freq["total_count"] == 5
    assert freq["unique_categories"] == 3
    assert freq["categories"][0]["category"] == "Cairo"
    assert freq["categories"][0]["count"] == 3
    assert freq["categories"][0]["percentage"] == 60.0


# ─── 7.4 ANOMALY DETECTION ENGINE TESTS ───


def test_anomaly_detection_iqr_zscore_and_pct():
    # Dataset with standard values around 100, and one massive outlier at 1000
    rows = [
        {"date": "2024-01-01", "sales": 100.0},
        {"date": "2024-01-02", "sales": 102.0},
        {"date": "2024-01-03", "sales": 98.0},
        {"date": "2024-01-04", "sales": 101.0},
        {"date": "2024-01-05", "sales": 99.0},
        {"date": "2024-01-06", "sales": 105.0},
        {"date": "2024-01-07", "sales": 1000.0},  # Clear Outlier
    ]

    anom_res = AnomalyDetectionEngine.detect_all(rows, metric_col="sales", label_col="date")
    assert len(anom_res["anomalies"]) > 0
    
    outlier = next(a for a in anom_res["anomalies"] if a["label"] == "2024-01-07")
    assert outlier["value"] == 1000.0
    # Flagged by IQR, Z-Score, and Percentage Deviation
    assert "IQR" in outlier["methods"] or "Z-Score" in outlier["methods"] or "Percentage_Deviation" in outlier["methods"]

    findings = AnomalyDetectionEngine.generate_findings(anom_res)
    assert any("2024-01-07" in f for f in findings)
