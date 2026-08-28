"""Unit tests for Evidence-Based Reporting in ReportService."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.report_service import ReportService
from app.services.analysis.models import AnalysisResult
from app.services.analytics.models import AnalyticsResult, DatasetSummary, NumericSummary, InsightResult, InsightItem, InsightSeverity
from app.agent.semantic.models import QuerySpec, AnalysisType, AnalysisOperation, AnalysisLevel


def test_format_evidence_payload_structure():
    service = ReportService()

    spec = QuerySpec(
        raw_question="ليه المبيعات انخفضت في الربع الأخير؟",
        analysis_type=AnalysisType.ROOT_CAUSE,
        analysis_goal="Identify drivers for Q4 sales drop",
        operations=[AnalysisOperation.ROOT_CAUSE, AnalysisOperation.TREND],
    )

    analysis_res = AnalysisResult(
        analysis_type="root_cause",
        goal="Identify drivers for Q4 sales drop",
        findings=["Sales dropped by 18.0% (-180,000 EGP)", "Region Cairo contributed 61.1% to the decline"],
        metrics={"q3_sales": 1000000.0, "q4_sales": 820000.0, "drop_amount": -180000.0},
        evidence=["Q4 sales = 820K vs Q3 sales = 1.0M", "Cairo dropped from 500K to 390K"],
        warnings=["Region Giza had positive growth (+10K) and was excluded"],
        limitations=["Marketing spend data is not present in schema"],
        confidence=0.98,
    )

    verified_facts = [
        {"statement": "Total revenue dropped by 180,000."},
        {"statement": "Cairo total sales is 390,000 in Q4."},
    ]

    payload = service._format_evidence_payload(
        question=spec.raw_question,
        query_spec=spec,
        analysis_result=analysis_res,
        verified_facts=verified_facts,
    )

    assert "ليه المبيعات انخفضت" in payload["question"]
    assert "Identify drivers" in payload["analysis_plan"]
    assert "Sales dropped by 18.0%" in payload["findings"]
    assert "Region Cairo contributed 61.1%" in payload["findings"]
    assert "q3_sales" in payload["metrics"]
    assert "Q4 sales = 820K" in payload["evidence"]
    assert "Cairo total sales is 390,000" in payload["verified_facts"]
    assert "Region Giza" in payload["warnings"]
    assert "Marketing spend data" in payload["limitations"]


@pytest.mark.asyncio
async def test_evidence_based_report_synthesis_flow():
    service = ReportService()

    spec = QuerySpec(
        raw_question="قارن المبيعات بين المناطق",
        analysis_type=AnalysisType.COMPARISON,
        analysis_goal="Compare sales across regions",
    )

    analysis_res = AnalysisResult(
        analysis_type="comparison",
        goal="Compare sales across regions",
        findings=["Cairo leads total sales with 500,000 EGP followed by Alex with 300,000 EGP"],
        metrics={"cairo_sales": 500000.0, "alex_sales": 300000.0},
        evidence=["Cairo = 500K, Alex = 300K"],
        confidence=1.0,
    )

    results = [
        {"region": "Cairo", "sales": 500000.0},
        {"region": "Alex", "sales": 300000.0},
    ]

    mock_llm_response = MagicMock()
    mock_llm_response.content = "بناءً على نتائج التحليل، تتصدر القاهرة إجمالي المبيعات بقيمة 500,000 جنيه، تليها الإسكندرية بقيمة 300,000 جنيه."

    with patch("app.services.report_service.get_langchain_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_llm_response)
        mock_get_llm.return_value = mock_llm

        report = await service.generate_report(
            question=spec.raw_question,
            sql="SELECT region, SUM(sales) AS sales FROM orders GROUP BY region",
            results=results,
            analysis_result=analysis_res,
            query_spec=spec,
            require_verification=True,
        )

    assert "القاهرة" in report
    assert "500,000" in report
    assert "300,000" in report
