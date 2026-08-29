"""Unit and Integration Tests for Phase 8: Evidence-Grounded Final Answer Composition.

Tests:
1. All numbers grounded (all numerical claims traceable to verified evidence items).
2. Unverified value handling (unverified items tagged with [unverified] or caveat without hallucination).
3. Incomplete investigation report (uncertainty language used instead of absolute claims).
4. Validation warnings in caveats (reconciliation/metric conflicts surfaced in limitations).
5. Supported root causes with provenance citations (source query and evidence IDs cited).
6. Simple query response (clean, concise format without bulky boilerplate).
7. Complex multi-query response (full structured executive sections).
8. Graph-level integration of GroundedReportComposer into AnalystAgent output.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.analysis.grounded_report_composer import (
    GroundedAnalysisContext,
    GroundedReportComposer,
)
from app.services.analysis.investigation_engine import InvestigationEngine
from app.services.analysis.investigation_models import (
    EvidenceItem,
    EvidenceType,
    Hypothesis,
    HypothesisStatus,
    InvestigationPlan,
    InvestigationState,
    InvestigationStatus,
    QueryExecutionRecord,
    QueryExecutionStatus,
    QueryTask,
    QueryTaskStatus,
    ValidationIssue,
    ValidationIssueType,
    ValidationSeverity,
)
from app.services.analysis.models import AnalysisPlan, AnalysisTask
from app.agent.orchestration.analyst_agent import AnalystAgent
from app.core.config.settings import settings
from app.agent.semantic.models import ExecutionRoute, IntentType, QueryUnderstanding
from app.utils.helpers import AnalysisType


# ─── Test 1: All Numbers Grounded ───

def test_1_all_numbers_grounded():
    """Test 1: Report derives all figures strictly from verified evidence."""
    ctx = GroundedAnalysisContext(
        original_question="What is the total revenue?",
        analytical_goal="Calculate revenue",
        verified_evidence=[
            EvidenceItem(
                evidence_id="ev_1",
                source_query_id="q_1",
                statement="Total revenue was $1,500,000 across 4 quarters",
                metric="revenue",
                value=1500000.0,
                verified=True,
            )
        ],
        confidence_score=0.95,
        completeness_score=100.0,
        is_simple_lookup=True,
    )

    report = GroundedReportComposer.compose(ctx, is_arabic=False)
    assert "$1,500,000" in report or "1,500,000" in report
    assert "q_1" in report


# ─── Test 2: Unverified Value Handling ───

def test_2_unverified_value_handling():
    """Test 2: Unverified items are tagged with [unverified] and caveats are listed."""
    ctx = GroundedAnalysisContext(
        original_question="Why did sales drop?",
        analytical_goal="Investigate sales decline",
        verified_evidence=[
            EvidenceItem(
                evidence_id="ev_1",
                source_query_id="q_1",
                statement="Sales dropped by 20%",
                metric="sales_drop",
                value=-20.0,
                verified=True,
            )
        ],
        unverified_evidence=[
            EvidenceItem(
                evidence_id="ev_unv",
                source_query_id="q_bad",
                statement="Marketing budget cut by 50%",
                metric="marketing_cut",
                value=-50.0,
                verified=False,
            )
        ],
        is_complete=False,
        completeness_score=60.0,
        confidence_score=0.50,
        is_simple_lookup=False,
    )

    report = GroundedReportComposer.compose(ctx, is_arabic=False)
    assert "[unverified]" in report or "unverified" in report.lower()
    assert "Caveats" in report or "Limitations" in report


# ─── Test 3: Incomplete Investigation Report ───

def test_3_incomplete_investigation_report_uncertainty():
    """Test 3: Incomplete investigation expresses uncertainty and does not make absolute causal claims."""
    ctx = GroundedAnalysisContext(
        original_question="Why did profit decline?",
        analytical_goal="Investigate profit drop",
        verified_evidence=[
            EvidenceItem(
                evidence_id="ev_1",
                source_query_id="q_1",
                statement="Gross profit fell by 15%",
                value=-15.0,
                verified=True,
            )
        ],
        is_complete=False,
        completeness_score=45.0,
        confidence_score=0.40,
        is_simple_lookup=False,
    )

    report_en = GroundedReportComposer.compose(ctx, is_arabic=False)
    assert "partially complete" in report_en or "preliminary" in report_en

    report_ar = GroundedReportComposer.compose(ctx, is_arabic=True)
    assert "غير مكتمل" in report_ar or "أولية" in report_ar


# ─── Test 4: Validation Warnings in Caveats ───

def test_4_validation_warnings_in_caveats():
    """Test 4: Discrepancies and validation warnings are surfaced in the Caveats section."""
    ctx = GroundedAnalysisContext(
        original_question="Category breakdown reconciliation",
        analytical_goal="Reconcile revenue",
        verified_evidence=[
            EvidenceItem(evidence_id="ev_1", source_query_id="q_1", statement="Total revenue is $10M", verified=True)
        ],
        validation_issues=[
            ValidationIssue(
                issue_id="iss_rec_1",
                type=ValidationIssueType.RECONCILIATION,
                severity=ValidationSeverity.WARNING,
                query_ids=["q_1", "q_2"],
                description="Category breakdown sum ($9M) is 10% lower than total ($10M).",
            )
        ],
        is_simple_lookup=False,
    )

    report = GroundedReportComposer.compose(ctx, is_arabic=False)
    assert "Reconciliation" in report or "reconciliation" in report
    assert "Category breakdown sum" in report


# ─── Test 5: Supported Root Causes with Provenance Citations ───

def test_5_supported_root_causes_with_provenance():
    """Test 5: Supported root causes cite source queries and evidence."""
    ctx = GroundedAnalysisContext(
        original_question="Why did revenue drop in Q3?",
        analytical_goal="Root cause analysis",
        verified_evidence=[
            EvidenceItem(
                evidence_id="ev_orders",
                source_query_id="q_orders",
                statement="Order volume fell by 30% in Q3",
                value=-30.0,
                verified=True,
            )
        ],
        hypotheses=[
            Hypothesis(
                hypothesis_id="h_vol",
                statement="Decline is volume-driven",
                status=HypothesisStatus.SUPPORTED,
                supporting_evidence=["Order volume fell by 30% in Q3"],
            ),
            Hypothesis(
                hypothesis_id="h_price",
                statement="Decline is price-driven",
                status=HypothesisStatus.REJECTED,
                contradicting_evidence=["Average selling price increased by 4%"],
            ),
        ],
        supported_root_causes=["Decline is volume-driven"],
        source_query_ids=["q_orders", "q_price"],
        is_simple_lookup=False,
    )

    report = GroundedReportComposer.compose(ctx, is_arabic=False)
    assert "Why It Changed" in report or "Root Cause" in report
    assert "Supported by evidence" in report
    assert "Rejected" in report
    assert "q_orders" in report


# ─── Test 6: Simple Query Clean Response ───

def test_6_simple_query_response():
    """Test 6: Simple single-step lookup returns concise answer without executive boilerplate."""
    ctx = GroundedAnalysisContext(
        original_question="How many active customers?",
        analytical_goal="Count customers",
        verified_evidence=[
            EvidenceItem(
                evidence_id="ev_1",
                source_query_id="q_cust",
                statement="There are 4,520 active customers.",
                metric="customer_count",
                value=4520,
                verified=True,
            )
        ],
        is_simple_lookup=True,
        confidence_score=1.0,
    )

    report = GroundedReportComposer.compose(ctx, is_arabic=False)
    assert "Direct Answer" in report or "Summary" in report
    assert "4,520" in report
    # Should not have complex multi-section headers
    assert "### 📌 Executive Answer" not in report
    assert "### 📊 What Changed" not in report


# ─── Test 7: Complex Multi-Query Structured Sections ───

def test_7_complex_multi_query_response_structure():
    """Test 7: Complex investigative queries produce all expected analytical sections."""
    ctx = GroundedAnalysisContext(
        original_question="Comprehensive Q3 performance investigation",
        analytical_goal="Full investigation",
        verified_evidence=[
            EvidenceItem(
                evidence_id="ev_1",
                source_query_id="q_1",
                statement="Total sales $2.5M",
                verified=True,
                evidence_type=EvidenceType.COMPARISON,
            )
        ],
        hypotheses=[
            Hypothesis(
                hypothesis_id="h_1",
                statement="Segment A drove the drop",
                status=HypothesisStatus.SUPPORTED,
            )
        ],
        source_query_ids=["q_1", "q_2"],
        is_simple_lookup=False,
    )

    report_ar = GroundedReportComposer.compose(ctx, is_arabic=True)
    assert "### 📌 الإجابة التنفيذية" in report_ar
    assert "### 🔍 النتائج الرئيسية" in report_ar
    assert "### 📊 ما الذي تغير؟" in report_ar
    assert "### 💡 أسباب ودوافع التغيير" in report_ar
    assert "### 📑 الأدلة والحقائق الموثقة" in report_ar
    assert "### 🎯 درجة الثقة والاكتمال" in report_ar


# ─── Test 8: Graph-Level Integration ───

@pytest.mark.asyncio
async def test_8_graph_grounded_report_integration():
    """Test 8: AnalystAgent end-to-end execution utilizes GroundedReportComposer."""
    agent = AnalystAgent()
    mock_db = MagicMock()

    mock_ctx = MagicMock()
    mock_ctx.schema = {"sales": {"columns": [{"name": "revenue", "type": "float"}]}}
    mock_ctx.catalog = None
    mock_ctx.total_tables = 1
    mock_ctx.total_columns = 1

    grounded = MagicMock()
    grounded.schema_text = "sales(revenue)"
    grounded.selected_tables = ["sales"]
    grounded.selected_columns = {"sales": ["revenue"]}
    grounded.retrieved_seed_tables = ["sales"]
    grounded.timings_ms = {}
    grounded.fallback_used = False

    spec = QueryUnderstanding(
        raw_question="What is the total revenue?",
        intent=IntentType.DATABASE,
        route=ExecutionRoute.DATA_QUERY,
        route_confidence=0.95,
        analysis_type=AnalysisType.EXPLORATORY_ANALYSIS,
        entities=["sales"],
        metrics=["sales.revenue"],
        dimensions=[],
        aggregations=["SUM"],
        confidence=0.95,
        source="deterministic",
    )

    custom_plan = AnalysisPlan(
        question="What is the total revenue?",
        analysis_goal="What is the total revenue?",
        tasks=[AnalysisTask(task_id="t1", name="Overall", required_query_tasks=["q_1"])],
        query_tasks=[QueryTask(query_id="q_1", purpose="Total sales", sub_question="Total sales", priority=1)],
    )

    async def fake_generate_sql(question, *args, **kwargs):
        return "SELECT SUM(revenue) FROM sales"

    async def fake_execute_with_repair(question, *args, **kwargs):
        return ([{"total_revenue": 1000000.0}], "SELECT SUM(revenue) FROM sales", None, None, [])

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock, return_value=spec), \
         patch("app.services.analysis.planner.AnalysisPlanner.plan", return_value=custom_plan), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock, return_value=grounded), \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.sql_generator, "execute_with_repair", side_effect=fake_execute_with_repair), \
         patch("app.services.report_service.ReportService.generate_report_and_chart", new_callable=AsyncMock, return_value=("Report", {})):

        res = await agent.ask("What is the total revenue?", db=mock_db)

    assert res["success"] is True
    assert "report" in res
    assert len(res["report"]) > 0
    assert "grounded_context" in res
    assert res["grounded_context"]["verified_evidence_count"] >= 1
