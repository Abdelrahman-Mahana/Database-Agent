"""Unit tests for Archetype-Specific Output Formatting in ReportService."""
import pytest
from app.services.report_service import ReportService
from app.services.analysis.models import AnalysisResult
from app.services.analytics.models import AnalyticsResult, DatasetSummary, NumericSummary, InsightResult, InsightItem, InsightSeverity
from app.agent.semantic.models import QuerySpec, AnalysisType, AnalysisOperation


def test_lookup_output_format():
    service = ReportService()
    spec = QuerySpec(raw_question="بيانات العميل أحمد", analysis_type=AnalysisType.LOOKUP)
    results = [{"name": "أحمد محمود", "phone": "01012345678", "city": "القاهرة"}]

    report = service._format_conversational_report(
        question=spec.raw_question,
        sql="SELECT * FROM customers WHERE name LIKE '%أحمد%'",
        results=results,
        query_spec=spec,
    )

    assert "الخلاصة:" in report
    assert "التفاصيل:" in report
    assert "أحمد محمود" in report
    assert "01012345678" in report


def test_metric_output_format():
    service = ReportService()
    spec = QuerySpec(raw_question="كم إجمالي المبيعات؟", analysis_type=AnalysisType.AGGREGATION)
    results = [{"total_sales": 1500000.0}]

    report = service._format_conversational_report(
        question=spec.raw_question,
        sql="SELECT SUM(sales) AS total_sales FROM orders",
        results=results,
        query_spec=spec,
    )

    assert "الخلاصة:" in report
    assert "1,500,000" in report
    assert "طريقة الحساب:" in report
    assert "SUM" in report or "المجموع" in report


def test_comparison_output_format():
    service = ReportService()
    spec = QuerySpec(raw_question="قارن بين القاهرة والإسكندرية", analysis_type=AnalysisType.COMPARISON)
    results = [
        {"city": "القاهرة", "sales": 500000.0},
        {"city": "الإسكندرية", "sales": 300000.0},
    ]

    report = service._format_conversational_report(
        question=spec.raw_question,
        sql="SELECT city, SUM(sales) FROM orders GROUP BY city",
        results=results,
        query_spec=spec,
    )

    assert "الخلاصة:" in report
    assert "مقارنة الأطراف:" in report
    assert "الطرف الأول" in report
    assert "الطرف الثاني" in report
    assert "الفارق" in report
    assert "المتصدر" in report
    assert "القاهرة" in report


def test_trend_output_format():
    service = ReportService()
    spec = QuerySpec(raw_question="كيف تطورت المبيعات الشهرية؟", analysis_type=AnalysisType.TREND)
    results = [
        {"month": "2024-01", "sales": 100000.0},
        {"month": "2024-02", "sales": 150000.0},
        {"month": "2024-03", "sales": 200000.0},
    ]

    analysis_res = AnalysisResult(
        analysis_type="trend",
        goal="Monthly sales trend",
        findings=["Sales increased steadily over Q1"],
        metrics={"trend_direction": "صاعد (Upward)", "growth_rate_pct": "+100.0%", "peak": "200,000", "lowest": "100,000"},
        confidence=1.0,
    )

    report = service._format_conversational_report(
        question=spec.raw_question,
        sql="SELECT month, sales FROM monthly_sales",
        results=results,
        query_spec=spec,
        analysis_result=analysis_res,
    )

    assert "الخلاصة:" in report
    assert "تحليل المسار الزمني:" in report
    assert "الاتجاه العام" in report
    assert "أعلى نقطة" in report
    assert "أدنى نقطة" in report
    assert "معدل النمو" in report


def test_root_cause_output_format():
    service = ReportService()
    spec = QuerySpec(raw_question="ما سبب انخفاض مبيعات الربع الرابع؟", analysis_type=AnalysisType.ROOT_CAUSE)
    results = [{"region": "القاهرة", "decline": -110000.0}]

    analysis_res = AnalysisResult(
        analysis_type="root_cause",
        goal="Q4 Decline RCA",
        findings=["تراجعت المبيعات بنسبة 18.0% (-180 ألف جنيه)", "منطقة القاهرة ساهمت بـ 61.1% من إجمالي التراجع"],
        metrics={"total_decline": -180000.0, "top_contributor": "القاهرة"},
        evidence=["مبيعات الربع الثالث 1.0M ومبيعات الربع الرابع 820K"],
        limitations=["بيانات الحملات التسويقية غير متوفرة في قاعدة البيانات"],
        confidence=0.97,
    )

    report = service._format_conversational_report(
        question=spec.raw_question,
        sql="SELECT region, SUM(sales) FROM sales_history GROUP BY region",
        results=results,
        query_spec=spec,
        analysis_result=analysis_res,
    )

    assert "الخلاصة:" in report
    assert "تحليل الأسباب والمساهمين:" in report
    assert "النتيجة الرئيسية" in report
    assert "أكبر المساهمين" in report
    assert "الأدلة الداعمة" in report
    assert "حدود التحليل" in report


def test_exploratory_analysis_output_format():
    service = ReportService()
    spec = QuerySpec(raw_question="حلل واستكشف جدول المبيعات", analysis_type=AnalysisType.EXPLORATORY_ANALYSIS)
    results = [{"id": 1, "product": "P1", "amount": 100.0}, {"id": 2, "product": "P2", "amount": 200.0}]

    analysis_res = AnalysisResult(
        analysis_type="exploratory_analysis",
        goal="Explore sales table",
        findings=["متوسط قيمة الطلب 150.0 جنيه"],
        metrics={"order_count": 2, "mean_amount": 150.0},
        evidence=["توزيع المبيعات منتظم"],
        warnings=["لا توجد سجلات مفقودة"],
        recommendations=["تطبيق تحليل الشرائح على العملاء"],
        confidence=1.0,
    )

    report = service._format_conversational_report(
        question=spec.raw_question,
        sql="SELECT * FROM sales",
        results=results,
        query_spec=spec,
        analysis_result=analysis_res,
    )

    assert "الخلاصة:" in report
    assert "التقرير الاستكشافي الشامل:" in report
    assert "نظرة عامة" in report
    assert "أهم النتائج" in report
    assert "الأنماط" in report
    assert "القيم الشاذة" in report
    assert "جودة البيانات" in report
    assert "التوصيات" in report
