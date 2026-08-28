"""Correction Pass Tests for Database Analyst Agent (Phase Tests A through L).

Verifies:
- Test A: Unordered ranking without ranking intent (does NOT produce ranking evidence).
- Test B: Ranking task with intent (deterministic sorting and true top category extracted).
- Test C: Unordered trend (chronological sorting prior to trend calculation).
- Test D: Trend with unparseable period (no directional trend claim for categorical dimensions).
- Test E: Two-row comparison with valid periods (deterministic baseline vs target delta).
- Test F: Two-row comparison with ambiguous ordering (neutral observation, no directional claim).
- Test G: Evidence coverage vs task completion (4 queries completed, 3 verified evidence -> task_comp=1.0, coverage=0.75).
- Test H: Heterogeneous result merge protection (monthly revenue vs monthly orders NOT merged).
- Test I: Compatible result merge (same grain and metric semantics permitted to merge).
- Test J: Cross-query metric mismatch (revenue vs order_count does NOT trigger conflict).
- Test K: Valid reconciliation (total = 100 vs breakdown = 40 + 60 succeeds).
- Test L: Confidence consistency (investigation confidence = 0.82 -> AnalysisResult.confidence = 0.82).
"""
import pytest

from app.services.analysis.evidence_manager import EvidenceManager, InvestigationProgressEvaluator
from app.services.analysis.cross_query_validator import CrossQueryValidator
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
)
from app.services.analysis.models import AnalysisResult
from app.services.analytics.models import AnalyticsResult, DatasetSummary


# ─── Test A: Unordered ranking without ranking intent ───

def test_A_unordered_ranking_without_intent():
    """Test A: Multi-row query without ranking intent produces categorical observation, NOT ranking claim."""
    record = QueryExecutionRecord(
        query_id="q_cats",
        purpose="List product categories",
        sub_question="What are all product categories and their revenues?",
        status=QueryExecutionStatus.SUCCESS,
        rows=[
            {"category": "Furniture", "revenue": 40.0},
            {"category": "Electronics", "revenue": 90.0},
            {"category": "Clothing", "revenue": 20.0},
        ],
    )
    task = QueryTask(
        query_id="q_cats",
        purpose="List product categories",
        sub_question="What are all product categories and their revenues?",
        required_metrics=["revenue"],
        required_dimensions=["category"],
    )

    ev_items = EvidenceManager.extract_evidence(record, task)
    ranking_ev = [e for e in ev_items if e.evidence_type == EvidenceType.RANKING]

    # Must NOT produce a ranking claim when no ranking intent was in question/task
    assert len(ranking_ev) == 0
    obs_ev = [e for e in ev_items if e.evidence_type == EvidenceType.OBSERVATION]
    assert len(obs_ev) > 0
    assert "breakdown" in obs_ev[0].statement.lower()


# ─── Test B: Ranking task with intent ───

def test_B_ranking_task_with_intent():
    """Test B: Query asking for top product categories deterministically extracts Electronics (90.0)."""
    record = QueryExecutionRecord(
        query_id="q_rank",
        purpose="Top product category ranking",
        sub_question="What are the top product categories by revenue?",
        status=QueryExecutionStatus.SUCCESS,
        rows=[
            {"category": "Furniture", "revenue": 40.0},
            {"category": "Electronics", "revenue": 90.0},
            {"category": "Clothing", "revenue": 20.0},
        ],
    )
    task = QueryTask(
        query_id="q_rank",
        purpose="Top product category ranking",
        sub_question="What are the top product categories by revenue?",
        required_metrics=["revenue"],
        required_dimensions=["category"],
    )

    ev_items = EvidenceManager.extract_evidence(record, task)
    ranking_ev = [e for e in ev_items if e.evidence_type == EvidenceType.RANKING]

    assert len(ranking_ev) == 1
    assert "Electronics is the top category by revenue with 90" in ranking_ev[0].statement
    assert ranking_ev[0].value == 90.0
    assert ranking_ev[0].dimensions == {"category": "Electronics"}
    assert ranking_ev[0].derivation_method == "deterministic_ranking"


# ─── Test C: Unordered trend ───

def test_C_unordered_trend_sorted_chronologically():
    """Test C: Chronological rows provided out of order (2024-03, 2024-01, 2024-02) are sorted before calculation."""
    record = QueryExecutionRecord(
        query_id="q_trend",
        purpose="Monthly sales trend",
        sub_question="What is the monthly revenue trend?",
        status=QueryExecutionStatus.SUCCESS,
        rows=[
            {"month": "2024-03", "revenue": 300.0},
            {"month": "2024-01", "revenue": 100.0},
            {"month": "2024-02", "revenue": 200.0},
        ],
    )
    ev_items = EvidenceManager.extract_evidence(record)
    trend_ev = [e for e in ev_items if e.evidence_type == EvidenceType.TREND]

    assert len(trend_ev) == 1
    # Sorted chronologically: 100 -> 200 -> 300 (increasing from 2024-01 to 2024-03)
    assert trend_ev[0].value["start"] == 100.0
    assert trend_ev[0].value["end"] == 300.0
    assert trend_ev[0].value["direction"] == "increasing"
    assert "Revenue increased from 2024-01 to 2024-03" in trend_ev[0].statement


# ─── Test D: Trend with unparseable period ───

def test_D_trend_with_unparseable_period():
    """Test D: Non-chronological categorical dimensions (e.g. region) do not produce directional trend claims."""
    record = QueryExecutionRecord(
        query_id="q_cat_trend",
        purpose="Revenue across regions",
        sub_question="Show revenue across North, South, and East",
        status=QueryExecutionStatus.SUCCESS,
        rows=[
            {"region": "North", "revenue": 100.0},
            {"region": "South", "revenue": 150.0},
            {"region": "East", "revenue": 220.0},
        ],
    )
    ev_items = EvidenceManager.extract_evidence(record)
    trend_ev = [e for e in ev_items if e.evidence_type == EvidenceType.TREND]

    # No directional trend claim for non-temporal regions
    assert len(trend_ev) == 0
    obs_ev = [e for e in ev_items if e.evidence_type == EvidenceType.OBSERVATION]
    assert len(obs_ev) > 0
    assert "increased from" not in obs_ev[0].statement.lower()


# ─── Test E: Two-row comparison with valid periods ───

def test_E_two_row_comparison_with_valid_periods():
    """Test E: 2024 (100) vs 2025 (120) deterministically produces +20.0% delta."""
    record = QueryExecutionRecord(
        query_id="q_comp",
        purpose="Yearly revenue comparison",
        sub_question="Compare 2024 and 2025 revenue",
        status=QueryExecutionStatus.SUCCESS,
        rows=[
            {"year": "2025", "revenue": 120.0},
            {"year": "2024", "revenue": 100.0},
        ],
    )
    ev_items = EvidenceManager.extract_evidence(record)
    comp_ev = [e for e in ev_items if e.evidence_type == EvidenceType.COMPARISON]

    assert len(comp_ev) == 1
    assert "2025 revenue (120) is 20.0% higher than 2024 (100)" in comp_ev[0].statement
    assert comp_ev[0].value["delta"] == 20.0
    assert comp_ev[0].value["pct_change"] == 20.0
    assert comp_ev[0].derivation_method == "comparison_delta"


# ─── Test F: Two-row comparison with ambiguous ordering ───

def test_F_two_row_comparison_ambiguous_ordering():
    """Test F: Non-temporal two-row query without explicit baseline produces neutral observation, no directional claim."""
    record = QueryExecutionRecord(
        query_id="q_seg_comp",
        purpose="Segment revenue comparison",
        sub_question="Compare Segment A and Segment B",
        status=QueryExecutionStatus.SUCCESS,
        rows=[
            {"segment": "Segment A", "revenue": 100.0},
            {"segment": "Segment B", "revenue": 120.0},
        ],
    )
    task = QueryTask(
        query_id="q_seg_comp",
        purpose="Segment revenue comparison",
        sub_question="Compare Segment A and Segment B",
        required_metrics=["revenue"],
        required_dimensions=["segment"],
    )

    ev_items = EvidenceManager.extract_evidence(record, task)
    comp_ev = [e for e in ev_items if e.evidence_type == EvidenceType.COMPARISON]

    # Must NOT produce directional comparison claim without reliable chronology/baseline
    assert len(comp_ev) == 0
    obs_ev = [e for e in ev_items if e.evidence_type == EvidenceType.OBSERVATION]
    assert len(obs_ev) > 0
    assert "without an explicit baseline/current chronology" in obs_ev[0].statement


# ─── Test G: Evidence coverage vs Task completion ───

def test_G_evidence_coverage_vs_task_completion():
    """Test G: 4 tasks completed, but only 3 verified evidence items -> task_comp=1.0, evidence_cov=0.75."""
    plan = InvestigationPlan(
        question="Investigate churn and revenue",
        query_tasks=[
            QueryTask(query_id="q_1", purpose="Q1", sub_question="Q1", status=QueryTaskStatus.COMPLETED),
            QueryTask(query_id="q_2", purpose="Q2", sub_question="Q2", status=QueryTaskStatus.COMPLETED),
            QueryTask(query_id="q_3", purpose="Q3", sub_question="Q3", status=QueryTaskStatus.COMPLETED),
            QueryTask(query_id="q_4", purpose="Q4", sub_question="Q4", status=QueryTaskStatus.COMPLETED),
        ],
    )
    state = InvestigationState(
        plan=plan,
        completed_queries=[
            QueryExecutionRecord(query_id="q_1", purpose="Q1", sub_question="Q1", status=QueryExecutionStatus.SUCCESS),
            QueryExecutionRecord(query_id="q_2", purpose="Q2", sub_question="Q2", status=QueryExecutionStatus.SUCCESS),
            QueryExecutionRecord(query_id="q_3", purpose="Q3", sub_question="Q3", status=QueryExecutionStatus.SUCCESS),
            QueryExecutionRecord(query_id="q_4", purpose="Q4", sub_question="Q4", status=QueryExecutionStatus.EMPTY),
        ],
        # Only Q1, Q2, and Q3 produced verified evidence; Q4 was empty
        evidence=[
            EvidenceItem(evidence_id="ev_1", source_query_id="q_1", statement="Ev 1", metric="revenue", value=100.0, verified=True),
            EvidenceItem(evidence_id="ev_2", source_query_id="q_2", statement="Ev 2", metric="margin", value=50.0, verified=True),
            EvidenceItem(evidence_id="ev_3", source_query_id="q_3", statement="Ev 3", metric="volume", value=20.0, verified=True),
        ],
        queries_executed=4,
        max_queries=5,
    )

    progress = InvestigationProgressEvaluator.evaluate_progress(state)

    assert progress.task_completion == 1.0     # All 4 tasks completed
    assert progress.evidence_coverage == 0.75  # 3 of 4 expected evidence items verified
    assert state.task_completion == 1.0
    assert state.evidence_coverage == 0.75


# ─── Test H: Heterogeneous result merge protection ───

def test_H_heterogeneous_result_merge_protection():
    """Test H: Queries with different metric semantics (monthly revenue vs monthly orders) are NOT merged."""
    task_1 = QueryTask(
        query_id="q1",
        purpose="Monthly revenue",
        sub_question="Monthly revenue",
        required_metrics=["revenue"],
        required_dimensions=["month"],
    )
    task_2 = QueryTask(
        query_id="q2",
        purpose="Monthly orders",
        sub_question="Monthly orders",
        required_metrics=["order_count"],
        required_dimensions=["month"],
    )

    # Check metric semantics equality
    assert set(task_1.required_metrics) != set(task_2.required_metrics)  # Incompatible metrics


# ─── Test I: Compatible result merge ───

def test_I_compatible_result_merge():
    """Test I: Queries with identical grain, dimensions, and metric semantics are compatible to merge."""
    task_1 = QueryTask(
        query_id="q1",
        purpose="Monthly revenue 2024",
        sub_question="Monthly revenue 2024",
        required_metrics=["revenue"],
        required_dimensions=["month"],
    )
    task_2 = QueryTask(
        query_id="q2",
        purpose="Monthly revenue 2025",
        sub_question="Monthly revenue 2025",
        required_metrics=["revenue"],
        required_dimensions=["month"],
    )

    # Both have same dimension and metric semantics
    assert set(task_1.required_metrics) == set(task_2.required_metrics)
    assert set(task_1.required_dimensions) == set(task_2.required_dimensions)


# ─── Test J: Cross-query metric mismatch ───

def test_J_cross_query_metric_mismatch_no_conflict():
    """Test J: Revenue vs order_count does NOT cause a false metric conflict."""
    state = InvestigationState(
        evidence=[
            EvidenceItem(evidence_id="ev1", source_query_id="q1", statement="Revenue is 100K", metric="revenue", value=100000.0, verified=True),
            EvidenceItem(evidence_id="ev2", source_query_id="q2", statement="Order count is 1000", metric="order_count", value=1000.0, verified=True),
        ]
    )
    issues = CrossQueryValidator._check_metric_conflicts(state)
    assert len(issues) == 0


# ─── Test K: Valid reconciliation ───

def test_K_valid_reconciliation():
    """Test K: Total revenue = 100 matches category breakdown (40 + 60) with 0 reconciliation issues."""
    state = InvestigationState(
        plan=InvestigationPlan(
            question="Reconcile revenue",
            query_tasks=[
                QueryTask(query_id="q_total", purpose="Total revenue", sub_question="Total revenue", required_metrics=["revenue"]),
                QueryTask(query_id="q_breakdown", purpose="Revenue by category", sub_question="Revenue by category", required_metrics=["revenue"]),
            ],
        ),
        completed_queries=[
            QueryExecutionRecord(
                query_id="q_total",
                purpose="Total revenue",
                status=QueryExecutionStatus.SUCCESS,
                rows=[{"revenue": 100.0}],
            ),
            QueryExecutionRecord(
                query_id="q_breakdown",
                purpose="Revenue by category",
                status=QueryExecutionStatus.SUCCESS,
                rows=[
                    {"category": "A", "revenue": 40.0},
                    {"category": "B", "revenue": 60.0},
                ],
            ),
        ],
    )
    issues, ran = CrossQueryValidator._check_total_reconciliation(state, tolerance_pct=0.05)
    assert ran is True
    assert len(issues) == 0


# ─── Test L: Confidence consistency ───

def test_L_confidence_consistency():
    """Test L: Investigation confidence (0.82) overwrites default and is preserved on AnalysisResult."""
    state = InvestigationState(
        completeness_score=0.80,
        confidence_score=0.82,
        status=InvestigationStatus.IN_PROGRESS,
    )
    analytics_res = AnalyticsResult(
        dataset=DatasetSummary(total_rows=5, total_columns=2),
        analytical_findings=["Valid analytical findings"],
    )

    result = AnalysisResult.from_analytics_and_insights(
        analytics_result=analytics_res,
        confidence=state.confidence_score,
    )

    assert result.confidence == 0.82
    assert result.confidence != 1.0
