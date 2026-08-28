"""Unit tests for Forecasting Engine and Statistical Testing Engine."""
import pytest
from app.services.analysis.engines.forecasting import ForecastingEngine
from app.services.analysis.engines.statistical_testing import StatisticalTestingEngine
from app.services.analysis.analyzers.forecasting import ForecastingAnalyzer
from app.services.analysis.analyzers.statistical_test import StatisticalTestAnalyzer
from app.agent.semantic.query_spec_builder import QuerySpecBuilder


# ─── FORECASTING ENGINE TESTS ───


def test_forecasting_linear_trend_upward():
    series = [
        ("2024-01", 100.0),
        ("2024-02", 110.0),
        ("2024-03", 120.0),
        ("2024-04", 130.0),
    ]

    res = ForecastingEngine.forecast_linear_trend(series, periods_ahead=3)
    assert res["slope"] == 10.0
    assert res["trend_direction"] == "upward"
    assert res["r_squared"] >= 0.99
    assert len(res["projections"]) == 3
    
    # Check projected values: t+1 should be 140, t+2 should be 150, t+3 should be 160
    assert res["projections"][0]["projected_value"] == 140.0
    assert res["projections"][1]["projected_value"] == 150.0
    assert res["projections"][2]["projected_value"] == 160.0


def test_forecasting_moving_average():
    series = [
        ("T1", 10.0),
        ("T2", 20.0),
        ("T3", 30.0),
    ]

    res = ForecastingEngine.forecast_moving_average(series, window=3, periods_ahead=2)
    assert res["sma_baseline"] == 20.0
    assert res["wma_baseline"] > 20.0  # WMA weights recent values more
    assert len(res["projections"]) == 2


def test_forecasting_all_models_and_findings():
    rows = [
        {"period": "2024-01", "sales": 1000.0},
        {"period": "2024-02", "sales": 1200.0},
        {"period": "2024-03", "sales": 1400.0},
    ]

    res = ForecastingEngine.forecast_all(rows, metric_col="sales", date_col="period", periods_ahead=3)
    assert res["last_observed_value"] == 1400.0
    assert res["recommended_next_period_value"] == 1600.0

    findings = ForecastingEngine.generate_findings(res)
    assert len(findings) >= 3
    assert any("1,600.00" in f for f in findings)


# ─── STATISTICAL TESTING ENGINE TESTS ───


def test_statistical_testing_welch_t_test_significant():
    # Significant difference between Cairo and Alexandria
    cairo_sales = [100.0, 105.0, 98.0, 102.0, 104.0, 101.0]
    alex_sales = [50.0, 52.0, 48.0, 55.0, 51.0, 49.0]

    res = StatisticalTestingEngine.two_sample_t_test(cairo_sales, alex_sales, name_a="Cairo", name_b="Alexandria")
    assert res["is_significant"] is True
    assert res["p_value"] < 0.001
    assert res["mean_difference"] > 45.0
    assert res["group_a"]["mean"] > 100.0
    assert res["group_b"]["mean"] < 55.0


def test_statistical_testing_welch_t_test_not_significant():
    # Non-significant difference
    group_1 = [100.0, 102.0, 99.0, 101.0]
    group_2 = [101.0, 100.0, 102.0, 98.0]

    res = StatisticalTestingEngine.two_sample_t_test(group_1, group_2, name_a="G1", name_b="G2")
    assert res["is_significant"] is False
    assert res["p_value"] > 0.05


def test_statistical_testing_mann_whitney_u():
    group_a = [10.0, 12.0, 14.0, 16.0]
    group_b = [1.0, 2.0, 3.0, 4.0]

    res = StatisticalTestingEngine.mann_whitney_u_test(group_a, group_b, name_a="A", name_b="B")
    assert res["is_significant"] is True
    assert res["u_statistic"] == 0.0


def test_statistical_testing_one_way_anova():
    groups = {
        "Cairo": [100.0, 105.0, 98.0, 102.0],
        "Alexandria": [80.0, 85.0, 78.0, 82.0],
        "Giza": [50.0, 55.0, 48.0, 52.0],
    }

    res = StatisticalTestingEngine.one_way_anova(groups)
    assert res["is_significant"] is True
    assert res["f_statistic"] > 10.0
    assert res["p_value"] < 0.01


def test_statistical_testing_chi_square():
    # Significant association between City and Product Preference
    rows = [
        {"city": "Cairo", "product": "Premium"},
        {"city": "Cairo", "product": "Premium"},
        {"city": "Cairo", "product": "Premium"},
        {"city": "Cairo", "product": "Basic"},
        {"city": "Alexandria", "product": "Basic"},
        {"city": "Alexandria", "product": "Basic"},
        {"city": "Alexandria", "product": "Basic"},
        {"city": "Alexandria", "product": "Premium"},
    ]

    res = StatisticalTestingEngine.chi_square_test(rows, col_a="city", col_b="product")
    assert res["test"] == "Chi-Square Test of Independence"
    assert res["degrees_of_freedom"] == 1
    assert "chi2_statistic" in res


def test_statistical_testing_auto_test_integration():
    rows = [
        {"city": "Cairo", "amount": 100.0},
        {"city": "Cairo", "amount": 105.0},
        {"city": "Alexandria", "amount": 50.0},
        {"city": "Alexandria", "amount": 55.0},
    ]

    res = StatisticalTestingEngine.auto_test(rows, metric_col="amount", group_col="city")
    assert res["test"] == "Welch's Two-Sample t-test"
    assert res["is_significant"] is True

    findings = StatisticalTestingEngine.generate_findings(res)
    assert any("Statistically Significant" in f for f in findings)
