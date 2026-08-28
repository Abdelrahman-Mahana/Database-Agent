"""Tests for Multi-Pillar Analysis Grounding."""
import pytest
from app.services.report_service import ReportService
from app.services.analysis.models import AnalysisResult
from app.agent.semantic.models import QuerySpec, AnalysisType, AnalysisOperation


def test_four_pillar_evidence_grounding_payload():
    service = ReportService()

    spec = QuerySpec(
        raw_question="قارن مبيعات الفروع وأسباب الفروقات",
        analysis_type=AnalysisType.COMPARISON,
        analysis_goal="Branch comparison and driver breakdown",
        operations=[AnalysisOperation.COMPARE, AnalysisOperation.ROOT_CAUSE],
    )

    analysis_res = AnalysisResult(
        analysis_type="comparison",
        goal="Branch comparison",
        findings=["فرع المعادي يتصدر المبيعات بـ 600 ألف"],
        metrics={"maadi_sales": 600000.0, "p_value": 0.002},
        evidence=["Maadi sales = 600K vs Nasr City = 400K"],
        warnings=["توزيع المبيعات غير متماثل"],
        limitations=["التحليل يقتصر على بيانات الشهر الحالي"],
        confidence=0.99,
    )

    verified_facts = [
        {"statement": "Maadi branch total sales is 600,000."},
        {"statement": "Nasr City branch total sales is 400,000."},
    ]

    payload = service._format_evidence_payload(
        question=spec.raw_question,
        query_spec=spec,
        analysis_result=analysis_res,
        verified_facts=verified_facts,
    )

    # 1. Goal & Plan
    assert "Branch comparison" in payload["analysis_plan"]
    # 2. Findings
    assert "المعادي" in payload["findings"]
    # 3. Metrics (Deterministic & Statistical)
    assert "maadi_sales" in payload["metrics"]
    assert "p_value" in payload["metrics"]
    # 4. Concrete Evidence
    assert "Maadi sales = 600K" in payload["evidence"]
    # 5. Verified Facts
    assert "Maadi branch total sales is 600,000" in payload["verified_facts"]
    # 6. Warnings & Limitations
    assert "غير متماثل" in payload["warnings"]
    assert "الشهر الحالي" in payload["limitations"]
