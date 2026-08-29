"""Unit and Integration Tests for Phase 7: Cross-Query Validation & Grounding Readiness.

Tests:
1. Exact reconciliation (aggregate total matches category sum exactly -> 0 issues).
2. Tolerance-based reconciliation (discrepancy within tolerance vs exceeding tolerance).
3. Metric conflicts (different query results for identical metric & dimensional context).
4. Time / grain mismatch (conflicting period definitions between related tasks).
5. Dimension mismatch (category definition inconsistencies / high unknown count).
6. Duplicate evidence detection (identical statements across distinct queries).
7. Completeness scoring (0–100 deterministic scale).
8. Confidence scoring (0.0–1.0 scale distinct from completeness).
9. Grounding readiness breakdown (verified vs unverified vs issue-flagged evidence).
10. Graph-level integration of cross-query validation into AnalystAgent output.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.analysis.cross_query_validator import (
    CrossQueryValidator,
    GroundingReadiness,
    ValidationReport,
)
from app.services.analysis.investigation_engine import InvestigationEngine
from app.services.analysis.investigation_models import (
    EvidenceItem,
    EvidenceType,
    InvestigationPlan,
    InvestigationState,
    InvestigationStatus,
    QueryExecutionRecord,
    QueryExecutionStatus,
    QueryTask,
    QueryTaskStatus,
    ValidationIssue,
    ValidationIssueStatus,
    ValidationIssueType,
    ValidationSeverity,
)
from app.services.analysis.models import AnalysisPlan, AnalysisTask
from app.agent.orchestration.analyst_agent import AnalystAgent
from app.core.config.settings import settings
from app.agent.semantic.models import ExecutionRoute, IntentType, QueryUnderstanding
from app.utils.helpers import AnalysisType


# ─── Test 1: Exact Total Reconciliation ───

def test_1_exact_total_reconciliation():
    """Test 1: Overall aggregate query matches the sum of category breakdown query exactly."""
    plan = InvestigationPlan(
        question="Total vs Categories",
        query_tasks=[
            QueryTask(query_id="q_total", purpose="Total revenue", sub_question="Total revenue"),
            QueryTask(query_id="q_cats", purpose="Category revenue", sub_question="Category revenue"),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)

    state.completed_queries = [
        QueryExecutionRecord(
            query_id="q_total",
            status=QueryExecutionStatus.SUCCESS,
            rows=[{"revenue": 1000000.0}],
        ),
        QueryExecutionRecord(
            query_id="q_cats",
            status=QueryExecutionStatus.SUCCESS,
            rows=[
                {"category": "Electronics", "revenue": 600000.0},
                {"category": "Furniture", "revenue": 400000.0},
            ],
        ),
    ]

    report = CrossQueryValidator.validate(state, tolerance_pct=0.05)
    rec_issues = [i for i in report.issues if i.type == ValidationIssueType.RECONCILIATION]
    assert len(rec_issues) == 0
    assert report.is_valid is True
    assert report.reconciliation_checked is True


# ─── Test 2: Tolerance-Based Reconciliation ───

def test_2_tolerance_based_reconciliation():
    """Test 2: Small discrepancy within 5% passes, but large discrepancy (e.g. 20%) triggers CRITICAL issue."""
    # Case A: Within tolerance (2% diff)
    state_a = InvestigationState(
        completed_queries=[
            QueryExecutionRecord(query_id="q_tot", status=QueryExecutionStatus.SUCCESS, rows=[{"revenue": 1000.0}]),
            QueryExecutionRecord(query_id="q_sub", status=QueryExecutionStatus.SUCCESS, rows=[{"cat": "A", "revenue": 980.0}]),
        ]
    )
    report_a = CrossQueryValidator.validate(state_a, tolerance_pct=0.05)
    rec_a = [i for i in report_a.issues if i.type == ValidationIssueType.RECONCILIATION]
    assert len(rec_a) == 0
    assert report_a.is_valid is True

    # Case B: Exceeds tolerance (20% diff -> 1000 vs 800)
    state_b = InvestigationState(
        completed_queries=[
            QueryExecutionRecord(query_id="q_tot", status=QueryExecutionStatus.SUCCESS, rows=[{"revenue": 1000.0}]),
            QueryExecutionRecord(query_id="q_sub", status=QueryExecutionStatus.SUCCESS, rows=[{"cat": "A", "revenue": 800.0}]),
        ]
    )
    report_b = CrossQueryValidator.validate(state_b, tolerance_pct=0.05)
    rec_b = [i for i in report_b.issues if i.type == ValidationIssueType.RECONCILIATION]
    assert len(rec_b) == 1
    assert rec_b[0].severity == ValidationSeverity.CRITICAL
    assert report_b.is_valid is False
    assert rec_b[0].expected == 1000.0
    assert rec_b[0].actual == 800.0


# ─── Test 3: Metric Conflict Detection ───

def test_3_metric_conflict_detection():
    """Test 3: Conflicting numeric values for the same metric in same dimensional context flags a conflict."""
    state = InvestigationState(
        evidence=[
            EvidenceItem(
                evidence_id="ev_1",
                source_query_id="q_1",
                statement="Total order_count = 1,000",
                metric="order_count",
                value=1000.0,
                dimensions={},
            ),
            EvidenceItem(
                evidence_id="ev_2",
                source_query_id="q_2",
                statement="Total order_count = 850",
                metric="order_count",
                value=850.0,
                dimensions={},
            ),
        ],
        completed_queries=[
            QueryExecutionRecord(query_id="q_1", status=QueryExecutionStatus.SUCCESS, rows=[{"order_count": 1000}]),
            QueryExecutionRecord(query_id="q_2", status=QueryExecutionStatus.SUCCESS, rows=[{"order_count": 850}]),
        ],
    )

    report = CrossQueryValidator.validate(state)
    conflict_issues = [i for i in report.issues if i.type == ValidationIssueType.METRIC_CONFLICT]
    assert len(conflict_issues) == 1
    assert conflict_issues[0].severity == ValidationSeverity.CRITICAL
    assert report.is_valid is False


# ─── Test 4: Time / Period Consistency Check ───

def test_4_time_period_mismatch():
    """Test 4: Related tasks under the same analysis task with conflicting expected grains are flagged."""
    plan = InvestigationPlan(
        question="Time grain test",
        query_tasks=[
            QueryTask(query_id="q_1", analytical_task_id="t_trend", purpose="P1", sub_question="Q1", expected_grain="monthly"),
            QueryTask(query_id="q_2", analytical_task_id="t_trend", purpose="P2", sub_question="Q2", expected_grain="quarterly"),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)
    state.completed_queries = [
        QueryExecutionRecord(query_id="q_1", status=QueryExecutionStatus.SUCCESS, rows=[{"val": 1}]),
        QueryExecutionRecord(query_id="q_2", status=QueryExecutionStatus.SUCCESS, rows=[{"val": 2}]),
    ]

    report = CrossQueryValidator.validate(state)
    time_issues = [i for i in report.issues if i.type == ValidationIssueType.TIME_MISMATCH]
    assert len(time_issues) == 1
    assert time_issues[0].severity == ValidationSeverity.WARNING
    assert "monthly" in time_issues[0].description and "quarterly" in time_issues[0].description


# ─── Test 5: Dimension Mismatch Check ───

def test_5_dimension_mismatch_check():
    """Test 5: Dimension breakdowns dominated by unknown/null values are flagged as INFO issue."""
    state = InvestigationState(
        completed_queries=[
            QueryExecutionRecord(
                query_id="q_dim",
                status=QueryExecutionStatus.SUCCESS,
                rows=[
                    {"category": "Unknown", "val": 10},
                    {"category": "None", "val": 20},
                    {"category": "Electronics", "val": 30},
                ],
            )
        ]
    )

    report = CrossQueryValidator.validate(state)
    dim_issues = [i for i in report.issues if i.type == ValidationIssueType.DIMENSION_MISMATCH]
    assert len(dim_issues) == 1
    assert dim_issues[0].severity == ValidationSeverity.INFO


# ─── Test 6: Duplicate Evidence Detection ───

def test_6_duplicate_evidence_detection():
    """Test 6: Multiple queries producing identical evidence statements are detected."""
    state = InvestigationState(
        evidence=[
            EvidenceItem(evidence_id="e1", source_query_id="q_1", statement="Total revenue = 1,000,000", metric="revenue", value=1000000.0),
            EvidenceItem(evidence_id="e2", source_query_id="q_2", statement="Total revenue = 1,000,000", metric="revenue", value=1000000.0),
        ],
        completed_queries=[
            QueryExecutionRecord(query_id="q_1", status=QueryExecutionStatus.SUCCESS, rows=[{"revenue": 1000000}]),
            QueryExecutionRecord(query_id="q_2", status=QueryExecutionStatus.SUCCESS, rows=[{"revenue": 1000000}]),
        ],
    )

    report = CrossQueryValidator.validate(state)
    dup_issues = [i for i in report.issues if i.type == ValidationIssueType.DUPLICATE_EVIDENCE]
    assert len(dup_issues) == 1
    assert dup_issues[0].severity == ValidationSeverity.INFO


# ─── Test 7: Deterministic Completeness Scoring (0–100 Scale) ───

def test_7_completeness_scoring():
    """Test 7: Completeness score is on 0-100 scale, reflecting task coverage and validation state."""
    # Fully completed plan with no issues
    plan = InvestigationPlan(
        question="Complete check",
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Q1", sub_question="Q1", status=QueryTaskStatus.COMPLETED),
            QueryTask(query_id="q_2", purpose="Q2", sub_question="Q2", status=QueryTaskStatus.COMPLETED),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)
    state.completeness_score = 1.0
    state.completed_queries = [
        QueryExecutionRecord(query_id="q_1", status=QueryExecutionStatus.SUCCESS, rows=[{"val": 1}]),
        QueryExecutionRecord(query_id="q_2", status=QueryExecutionStatus.SUCCESS, rows=[{"val": 2}]),
    ]

    report = CrossQueryValidator.validate(state)
    assert report.completeness_score == 100.0

    # Half completed plan
    plan_half = InvestigationPlan(
        question="Half check",
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Q1", sub_question="Q1", status=QueryTaskStatus.COMPLETED),
            QueryTask(query_id="q_2", purpose="Q2", sub_question="Q2", status=QueryTaskStatus.PENDING),
        ],
    )
    state_half = InvestigationEngine.initialize_investigation(plan_half)
    state_half.completeness_score = 0.5
    state_half.completed_queries = [
        QueryExecutionRecord(query_id="q_1", status=QueryExecutionStatus.SUCCESS, rows=[{"val": 1}]),
    ]

    report_half = CrossQueryValidator.validate(state_half)
    assert 40.0 <= report_half.completeness_score <= 65.0


# ─── Test 8: Deterministic Confidence Scoring (0.0–1.0 Scale) ───

def test_8_confidence_scoring_distinct_from_completeness():
    """Test 8: Confidence score is distinct from completeness; critical issues reduce confidence sharply."""
    # Plan is 100% complete, BUT has a critical metric conflict
    plan = InvestigationPlan(
        question="Conflict plan",
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Q1", sub_question="Q1", status=QueryTaskStatus.COMPLETED),
            QueryTask(query_id="q_2", purpose="Q2", sub_question="Q2", status=QueryTaskStatus.COMPLETED),
        ],
    )
    state = InvestigationEngine.initialize_investigation(plan)
    state.completeness_score = 1.0
    state.evidence = [
        EvidenceItem(evidence_id="e1", source_query_id="q_1", statement="Rev=100", metric="rev", value=100.0),
        EvidenceItem(evidence_id="e2", source_query_id="q_2", statement="Rev=50", metric="rev", value=50.0),
    ]
    state.completed_queries = [
        QueryExecutionRecord(query_id="q_1", status=QueryExecutionStatus.SUCCESS, rows=[{"rev": 100}]),
        QueryExecutionRecord(query_id="q_2", status=QueryExecutionStatus.SUCCESS, rows=[{"rev": 50}]),
    ]

    report = CrossQueryValidator.validate(state)
    # Completeness remains high because tasks completed
    assert report.completeness_score >= 80.0
    # Confidence drops significantly due to critical conflict
    assert report.confidence_score <= 0.50
    assert report.confidence_score != report.completeness_score


# ─── Test 9: Grounding Readiness Breakdown ───

def test_9_grounding_readiness_breakdown():
    """Test 9: Facts with critical issues are separated from verified facts."""
    state = InvestigationState(
        evidence=[
            EvidenceItem(evidence_id="e_good", source_query_id="q_ok", statement="Good fact", metric="m1", value=10.0, verified=True, confidence=0.9),
            EvidenceItem(evidence_id="e_bad", source_query_id="q_bad", statement="Conflict fact", metric="rev", value=20.0, verified=True, confidence=0.9),
            EvidenceItem(evidence_id="e_bad2", source_query_id="q_bad2", statement="Conflict fact 2", metric="rev", value=40.0, verified=True, confidence=0.9),
        ],
        completed_queries=[
            QueryExecutionRecord(query_id="q_ok", status=QueryExecutionStatus.SUCCESS, rows=[{"m1": 10}]),
            QueryExecutionRecord(query_id="q_bad", status=QueryExecutionStatus.SUCCESS, rows=[{"rev": 20}]),
            QueryExecutionRecord(query_id="q_bad2", status=QueryExecutionStatus.SUCCESS, rows=[{"rev": 40}]),
        ],
    )

    report = CrossQueryValidator.validate(state)
    readiness = report.grounding_readiness

    assert len(readiness.verified_facts) == 1
    assert readiness.verified_facts[0].evidence_id == "e_good"
    assert len(readiness.unverified_facts) == 2
    assert readiness.is_ready_for_report is False


# ─── Test 10: Graph-Level Cross-Query Validation Integration ───

@pytest.mark.asyncio
async def test_10_graph_cross_query_validation_integration():
    """Test 10: AnalystAgent outputs cross_query_validation, completeness_score, and confidence_score."""
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
        raw_question="Analyze sales",
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
        question="Analyze sales",
        analysis_goal="Analyze sales",
        tasks=[AnalysisTask(task_id="t1", name="Overall", required_query_tasks=["q_1"])],
        query_tasks=[QueryTask(query_id="q_1", purpose="Total sales", sub_question="Total sales", priority=1)],
    )

    async def fake_generate_sql(question, *args, **kwargs):
        return "SELECT SUM(revenue) FROM sales"

    async def fake_execute_with_repair(question, *args, **kwargs):
        return ([{"total_revenue": 500000.0}], "SELECT SUM(revenue) FROM sales", None, None, [])

    with patch.object(settings, "use_langgraph_orchestrator", True), \
         patch.object(agent.schema_service, "get_database_context", return_value=mock_ctx), \
         patch.object(agent.query_spec_builder, "build_spec_async", new_callable=AsyncMock, return_value=spec), \
         patch("app.services.analysis.planner.AnalysisPlanner.plan", return_value=custom_plan), \
         patch.object(agent.schema_grounding_engine, "build_grounded_schema_async", new_callable=AsyncMock, return_value=grounded), \
         patch.object(agent.sql_generator, "generate_sql", side_effect=fake_generate_sql), \
         patch.object(agent.sql_generator, "execute_with_repair", side_effect=fake_execute_with_repair), \
         patch.object(agent.report_service, "generate_report_and_chart", new_callable=AsyncMock, return_value=("Report", {})):

        res = await agent.ask("Analyze sales", db=mock_db)

    assert res["success"] is True
    assert "cross_query_validation" in res
    assert "completeness_score" in res
    assert res["completeness_score"] == 100.0
    assert "confidence_score" in res
    assert res["confidence_score"] > 0.0
    assert "grounding_readiness" in res
    assert res["grounding_readiness"]["is_ready_for_report"] is True
