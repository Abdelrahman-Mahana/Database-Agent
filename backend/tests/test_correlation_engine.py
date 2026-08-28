"""Unit tests for the Correlation Engine and CorrelationAnalyzer.

Verifies the 6 steps:
1. Retrieve variable X (e.g. price)
2. Retrieve variable Y (e.g. quantity)
3. Calculate Pearson correlation (r) & determination (R²)
4. Determine direction (positive, negative/inverse, neutral)
5. Determine strength (very strong, strong, moderate, weak, negligible)
6. Explain limitations (causality disclaimers, linear association caveats, sample size)
"""
import pytest
from app.services.analysis.engines.correlation import CorrelationEngine
from app.services.analysis.analyzers.correlation import CorrelationAnalyzer
from app.services.analysis.models import AnalysisTask
from app.agent.semantic.models import AnalysisOperation, QuerySpec
from app.agent.semantic.query_spec_builder import QuerySpecBuilder


def test_correlation_negative_price_vs_quantity():
    # Strong inverse relationship: as price increases, quantity demanded drops
    rows = [
        {"price": 10.0, "quantity": 100.0},
        {"price": 20.0, "quantity": 80.0},
        {"price": 30.0, "quantity": 60.0},
        {"price": 40.0, "quantity": 40.0},
        {"price": 50.0, "quantity": 20.0},
    ]

    res = CorrelationEngine.compute_correlation(rows, col_x="price", col_y="quantity")
    
    # 1 & 2. Variables paired
    assert res["col_x"] == "price"
    assert res["col_y"] == "quantity"
    assert res["sample_size"] == 5

    # 3. Pearson r and R²
    assert res["pearson_r"] == -1.0  # Perfect inverse linear relationship
    assert res["r_squared"] == 1.0
    assert res["variance_explained_pct"] == 100.0

    # 4. Direction
    assert res["direction"] == "negative"
    assert "عكسية" in res["direction_desc"]

    # 5. Strength
    assert res["strength"] == "very_strong"
    assert "قوية جداً" in res["strength_desc"]

    # 6. Limitations explained
    assert len(res["limitations"]) >= 2
    assert any("السببية" in lim or "causation" in lim.lower() for lim in res["limitations"])
    assert any("الخطية" in lim or "linear" in lim.lower() for lim in res["limitations"])


def test_correlation_positive_relationship():
    # Strong positive relationship
    rows = [
        {"marketing_spend": 1000.0, "revenue": 5000.0},
        {"marketing_spend": 2000.0, "revenue": 9500.0},
        {"marketing_spend": 3000.0, "revenue": 14000.0},
        {"marketing_spend": 4000.0, "revenue": 18500.0},
    ]

    res = CorrelationEngine.compute_correlation(rows, col_x="marketing_spend", col_y="revenue")
    assert res["pearson_r"] > 0.95
    assert res["direction"] == "positive"
    assert "طردية" in res["direction_desc"]
    assert res["strength"] in ("strong", "very_strong")


def test_correlation_negligible_relationship():
    # Random uncoordinated data points
    rows = [
        {"x": 10.0, "y": 50.0},
        {"x": 20.0, "y": 10.0},
        {"x": 30.0, "y": 80.0},
        {"x": 40.0, "y": 20.0},
        {"x": 50.0, "y": 60.0},
    ]

    res = CorrelationEngine.compute_correlation(rows, col_x="x", col_y="y")
    assert abs(res["pearson_r"]) < 0.4
    assert res["strength"] in ("weak", "negligible")


def test_correlation_analyzer_execution_and_findings():
    analyzer = CorrelationAnalyzer()
    builder = QuerySpecBuilder()
    spec = builder.build_spec("هل السعر مرتبط بالكمية؟")
    
    tasks, reqs, insights = analyzer.plan_tasks(spec)
    assert len(tasks) == 1
    assert len(reqs) == 1
    assert any("Pearson" in ins for ins in insights)

    rows = [
        {"price": 10.0, "quantity": 100.0},
        {"price": 20.0, "quantity": 50.0},
        {"price": 30.0, "quantity": 33.0},
        {"price": 40.0, "quantity": 25.0},
    ]

    task_res = analyzer.execute(tasks[0], rows, numeric_cols=["price", "quantity"], dimension_cols=[])
    assert task_res.status == "completed"
    assert "pearson_r" in task_res.computed_metrics
    assert task_res.computed_metrics["direction"] == "negative"
    
    # Check that findings contain clear structured points without requiring LLM calculation
    findings_text = "\n".join(task_res.findings)
    assert "بيرسون" in findings_text
    assert "عكسية" in findings_text
    assert "القيود المنهجية" in findings_text
