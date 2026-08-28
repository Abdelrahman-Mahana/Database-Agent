"""Unit tests for the Data Quality Engine and DataQualityAnalyzer across all 7 dimensions."""
import pytest
from app.services.analysis.engines.data_quality import DataQualityEngine
from app.services.analysis.analyzers.data_quality import DataQualityAnalyzer
from app.agent.semantic.query_spec_builder import QuerySpecBuilder


def test_data_quality_missing_and_completeness():
    rows = [
        {"id": 1, "name": "Ahmed", "city": "Cairo", "salary": 5000.0},
        {"id": 2, "name": "", "city": "Alexandria", "salary": None},
        {"id": 3, "name": "Mona", "city": "NULL", "salary": 6000.0},
    ]

    res = DataQualityEngine.check_missing_values(rows)
    assert res["total_rows"] == 3
    assert res["total_missing_cells"] == 3  # empty name, None salary, 'NULL' city
    assert res["overall_completeness_pct"] == 75.0  # 9/12 = 75%


def test_data_quality_duplicates():
    rows = [
        {"id": 1, "name": "Ahmed"},
        {"id": 2, "name": "Sara"},
        {"id": 1, "name": "Ahmed"},  # Exact duplicate
    ]

    res = DataQualityEngine.check_duplicate_rows(rows)
    assert res["total_rows"] == 3
    assert res["duplicate_count"] == 1
    assert res["unique_rows"] == 2
    assert res["duplicate_pct"] == 33.33


def test_data_quality_invalid_ranges():
    rows = [
        {"item": "A", "price": 100.0, "quantity": 5},
        {"item": "B", "price": -20.0, "quantity": -2},  # Negative price & quantity
    ]

    res = DataQualityEngine.check_invalid_ranges(rows)
    assert res["total_violations"] == 2
    cols_violated = [v["column"] for v in res["violations"]]
    assert "price" in cols_violated
    assert "quantity" in cols_violated


def test_data_quality_high_cardinality():
    rows = [
        {"code": "C1", "description": "Desc 1"},
        {"code": "C2", "description": "Desc 2"},
        {"code": "C3", "description": "Desc 3"},
        {"code": "C4", "description": "Desc 4"},
        {"code": "C5", "description": "Desc 5"},
        {"code": "C6", "description": "Desc 6"},
    ]

    res = DataQualityEngine.check_high_cardinality(rows)
    assert len(res["high_cardinality_columns"]) == 1
    assert res["high_cardinality_columns"][0]["column"] == "description"


def test_data_quality_low_variance():
    rows = [
        {"country": "Egypt", "status": "active", "vat_rate": 0.14},
        {"country": "Egypt", "status": "active", "vat_rate": 0.14},
        {"country": "Egypt", "status": "active", "vat_rate": 0.14},
    ]

    res = DataQualityEngine.check_low_variance(rows)
    low_cols = [c["column"] for c in res["low_variance_columns"]]
    assert "country" in low_cols
    assert "status" in low_cols
    assert "vat_rate" in low_cols


def test_data_quality_inconsistent_categories():
    rows = [
        {"country": "Egypt"},
        {"country": "egypt"},  # Casing inconsistency
        {"country": "EGYPT"},  # Casing inconsistency
        {"country": " Saudi Arabia "},  # Whitespace issue
    ]

    res = DataQualityEngine.check_inconsistent_categories(rows)
    assert len(res["inconsistencies"]) == 1
    inc = res["inconsistencies"][0]
    assert inc["column"] == "country"
    assert "egypt" in inc["casing_conflicts"]
    assert len(inc["casing_conflicts"]["egypt"]) == 3
    assert inc["whitespace_issues_count"] == 1


def test_data_quality_full_audit_and_score():
    rows = [
        {"id": 1, "item": "A", "price": 100.0, "status": "active"},
        {"id": 2, "item": "B", "price": 200.0, "status": "active"},
        {"id": 3, "item": "C", "price": 150.0, "status": "active"},
    ]

    audit = DataQualityEngine.audit_dataset(rows)
    assert audit["overall_quality_score"] >= 90.0
    assert audit["total_rows"] == 3
    
    findings = DataQualityEngine.generate_findings(audit)
    findings_text = "\n".join(findings)
    assert "تقرير جودة واكتمال البيانات" in findings_text
    assert "نسبة الاكتمال الكلية" in findings_text


def test_data_quality_analyzer_integration():
    analyzer = DataQualityAnalyzer()
    builder = QuerySpecBuilder()
    spec = builder.build_spec("تحقق من جودة البيانات")

    tasks, reqs, insights = analyzer.plan_tasks(spec)
    assert len(tasks) == 1
    assert any("Quality Score" in ins for ins in insights)

    rows = [
        {"name": "Ahmed", "age": 30},
        {"name": None, "age": -5},
    ]

    task_res = analyzer.execute(tasks[0], rows, numeric_cols=["age"], dimension_cols=["name"])
    assert task_res.status == "completed"
    assert "overall_quality_score" in task_res.computed_metrics
    assert len(task_res.findings) > 0
