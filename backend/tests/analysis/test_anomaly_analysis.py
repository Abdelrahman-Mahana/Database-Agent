"""Tests for Anomaly Detection Engine."""
import pytest
from app.services.analysis.engines.anomaly_detection import AnomalyDetectionEngine


def test_anomaly_detection_iqr_zscore_and_pct():
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
    assert len(outlier["methods"]) >= 1
