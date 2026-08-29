"""Unit tests for the Root Cause Analysis (RCA) Engine and RootCauseAnalyzer.

Verifies the full Root Cause Investigation Pipeline:
1. Overall decline quantification (e.g. Sales down 18%)
2. Time window isolation
3. Dimensional comparison (Region, Product, Segment)
4. Finding largest contributors
5. Isolating negative changes
6. Ranking contributors with percentage contribution share
7. Generating verified mathematical evidence
"""
import pytest
from app.services.analysis.engines import RootCauseEngine
from app.services.analysis.analyzers import RootCauseAnalyzer
from app.agent.semantic.query_spec_builder import QuerySpecBuilder


def test_root_cause_overall_decline_quantification():
    rows = [
        {"period": "2024", "sales": 100000.0},
        {"period": "2025", "sales": 82000.0},  # 18% decline
    ]

    res = RootCauseEngine.quantify_overall_decline(rows, metric_col="sales", time_col="period")
    assert res["has_decline"] is True
    assert res["prior_period"] == "2024"
    assert res["current_period"] == "2025"
    assert res["prior_value"] == 100000.0
    assert res["current_value"] == 82000.0
    assert res["total_change"] == -18000.0
    assert res["growth_pct"] == -18.0


def test_root_cause_dimensional_decomposition_and_ranking():
    # Multi-period breakdown per region showing regional contributions to the 18k drop
    rows = [
        {"period": "2024", "region": "Region A", "sales": 50000.0},
        {"period": "2025", "region": "Region A", "sales": 39000.0},  # Delta: -11,000 (61.1% of drop)

        {"period": "2024", "region": "Region B", "sales": 30000.0},
        {"period": "2025", "region": "Region B", "sales": 25000.0},  # Delta: -5,000 (27.8% of drop)

        {"period": "2024", "region": "Region C", "sales": 20000.0},
        {"period": "2025", "region": "Region C", "sales": 18000.0},  # Delta: -2,000 (11.1% of drop)
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
    
    # 1st ranked driver: Region A
    top_driver = decomp["negative_contributors"][0]
    assert top_driver["category"] == "Region A"
    assert top_driver["delta"] == -11000.0
    assert top_driver["contribution_to_decline_pct"] == 61.11

    # 2nd ranked driver: Region B
    second_driver = decomp["negative_contributors"][1]
    assert second_driver["category"] == "Region B"
    assert second_driver["delta"] == -5000.0
    assert second_driver["contribution_to_decline_pct"] == 27.78

    # 3rd ranked driver: Region C
    third_driver = decomp["negative_contributors"][2]
    assert third_driver["category"] == "Region C"
    assert third_driver["delta"] == -2000.0
    assert third_driver["contribution_to_decline_pct"] == 11.11


def test_root_cause_full_investigation_and_findings():
    # Multi-dimensional dataset with products and branches
    rows = [
        {"period": "2024-Q1", "product": "Product X", "sales": 40000.0},
        {"period": "2024-Q2", "product": "Product X", "sales": 32000.0},  # -8000 drop

        {"period": "2024-Q1", "product": "Product Y", "sales": 30000.0},
        {"period": "2024-Q2", "product": "Product Y", "sales": 24000.0},  # -6000 drop

        {"period": "2024-Q1", "product": "Product Z", "sales": 10000.0},
        {"period": "2024-Q2", "product": "Product Z", "sales": 12000.0},  # +2000 gain (positive)
    ]

    investigation = RootCauseEngine.run_investigation(
        rows=rows,
        metric_col="sales",
        dimension_cols=["product"],
        time_col="period",
    )

    findings = RootCauseEngine.generate_findings(investigation)
    findings_text = "\n".join(findings)

    assert "Product X" in findings_text
    assert "Product Y" in findings_text
    assert "-8,000.00" in findings_text
    assert "التراجع الإجمالي" in findings_text


def test_root_cause_analyzer_integration():
    analyzer = RootCauseAnalyzer()
    builder = QuerySpecBuilder()
    spec = builder.build_spec("ليه المبيعات انخفضت؟")

    tasks, reqs, insights = analyzer.plan_tasks(spec)
    assert len(tasks) == 2
    assert any("Ranked" in ins or "Grounded" in ins for ins in insights)

    rows = [
        {"period": "2024", "department": "Cardiology", "sales": 50000.0},
        {"period": "2025", "department": "Cardiology", "sales": 35000.0},
        {"period": "2024", "department": "Dentistry", "sales": 20000.0},
        {"period": "2025", "department": "Dentistry", "sales": 15000.0},
    ]

    task_res = analyzer.execute(
        task=tasks[1],
        rows=rows,
        numeric_cols=["sales"],
        dimension_cols=["period", "department"],
    )

    assert task_res.status == "completed"
    assert len(task_res.findings) > 0
    assert "Cardiology" in str(task_res.findings)
