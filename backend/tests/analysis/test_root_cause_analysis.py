"""Tests for Root Cause Analysis Engine."""
import pytest
from app.services.analysis.engines import RootCauseEngine


def test_root_cause_engine_dimensional_decomposition():
    rows = [
        {"period": "2024", "region": "Cairo", "sales": 50000.0},
        {"period": "2025", "region": "Cairo", "sales": 39000.0},  # Delta: -11,000 (61.1% of drop)

        {"period": "2024", "region": "Alexandria", "sales": 30000.0},
        {"period": "2025", "region": "Alexandria", "sales": 25000.0},  # Delta: -5,000 (27.8% of drop)

        {"period": "2024", "region": "Giza", "sales": 20000.0},
        {"period": "2025", "region": "Giza", "sales": 18000.0},  # Delta: -2,000 (11.1% of drop)
    ]

    decomp = RootCauseEngine.decompose_dimension(
        rows,
        dimension_col="region",
        metric_col="sales",
        time_col="period",
        total_decline=-18000.0,
    )

    assert decomp["dimension"] == "region"
    assert len(decomp["negative_contributors"]) == 3

    top_driver = decomp["negative_contributors"][0]
    assert top_driver["category"] == "Cairo"
    assert top_driver["delta"] == -11000.0
    assert top_driver["contribution_to_decline_pct"] == pytest.approx(61.11, rel=0.01)

    inv = RootCauseEngine.run_investigation(
        rows,
        metric_col="sales",
        dimension_cols=["region"],
        time_col="period",
    )
    findings = RootCauseEngine.generate_findings(inv)
    assert len(findings) >= 2
