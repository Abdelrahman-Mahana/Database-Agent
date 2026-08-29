"""Tests for Analysis Routing and Intent Classification."""
import pytest
from app.agent.semantic.models import QuerySpec, AnalysisType, AnalysisOperation, AnalysisLevel
from app.services.report_service import ReportService, ReportMode
from app.utils.helpers import COMPLEX_ANALYSIS_TYPES


def test_complex_vs_simple_analysis_routing():
    service = ReportService()

    # Simple scalar/lookup routing
    lookup_spec = QuerySpec(raw_question="بيانات المريض رقم 10", analysis_type=AnalysisType.LOOKUP)
    assert service.resolve_report_mode(lookup_spec) == ReportMode.DETERMINISTIC

    count_spec = QuerySpec(raw_question="كم عدد الأطباء؟", analysis_type=AnalysisType.COUNT)
    assert service.resolve_report_mode(count_spec) == ReportMode.DETERMINISTIC

    # Complex analytical routing
    comparison_spec = QuerySpec(raw_question="قارن بين الفروع", analysis_type=AnalysisType.COMPARISON)
    assert service.resolve_report_mode(comparison_spec) == ReportMode.SYNTHESIS

    trend_spec = QuerySpec(raw_question="تطور المبيعات شهريا", analysis_type=AnalysisType.TREND)
    assert service.resolve_report_mode(trend_spec) == ReportMode.SYNTHESIS

    rca_spec = QuerySpec(raw_question="ليه المبيعات قلت في Q4؟", analysis_type=AnalysisType.ROOT_CAUSE)
    assert service.resolve_report_mode(rca_spec) == ReportMode.SYNTHESIS


def test_all_17_analysis_types_coverage():
    all_types = list(AnalysisType)
    assert len(all_types) >= 17

    for at in [
        AnalysisType.COMPARISON,
        AnalysisType.TREND,
        AnalysisType.ROOT_CAUSE,
        AnalysisType.CORRELATION,
        AnalysisType.ANOMALY_DETECTION,
        AnalysisType.EXPLORATORY_ANALYSIS,
    ]:
        assert at in COMPLEX_ANALYSIS_TYPES
