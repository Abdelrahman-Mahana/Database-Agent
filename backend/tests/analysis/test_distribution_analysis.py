"""Tests for Distribution Analysis Engine."""
import pytest
from app.services.analysis.engines import DistributionEngine


def test_distribution_percentiles_and_buckets():
    rows = [{"score": float(i)} for i in range(1, 101)]

    result = DistributionEngine.compute_numeric_distribution(rows, numeric_col="score", num_buckets=5)

    assert result["count"] == 100
    assert result["mean"] == 50.5
    assert result["median"] == 50.5
    assert result["percentiles"]["p25"] < result["percentiles"]["p50"] < result["percentiles"]["p75"]
    assert len(result["buckets"]) == 5
    assert sum(b["count"] for b in result["buckets"]) == 100
