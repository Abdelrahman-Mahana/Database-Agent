"""Unit and Integration Tests for Phase 6: Controlled Hypothesis Investigation for Root-Cause Questions.

Tests:
1. Hypothesis creation & generation (structured typed hypotheses with PROPOSED status).
2. Hypothesis support (verified evidence confirming volume or driver hypothesis).
3. Hypothesis rejection (verified evidence disproving price or driver hypothesis).
4. Contradiction & mixed evidence (results in INCONCLUSIVE with mixed evidence references).
5. Incomplete evidence (no relevant evidence results in INCONCLUSIVE with 0.0 confidence).
6. Deterministic numerical contribution calculation (baseline, current, delta, share of drop).
7. Multiple root causes identification (multiple segments flagged with percentage contribution).
8. No root cause identifiable (all positive/flat returns empty drivers without hallucination).
9. Deterministic hypothesis ranking (SUPPORTED > INCONCLUSIVE > REJECTED).
10. RootCauseAnalyzer integration (end-to-end analyzer execution with contribution analysis).
11. InvestigationState hypothesis lifecycle (state tracks and updates active hypotheses).
"""
import pytest
from unittest.mock import MagicMock

from app.services.analysis.hypothesis_manager import (
    HypothesisManager,
    SegmentContribution,
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
    QueryTask,
    QueryTaskStatus,
)
from app.services.analysis.analyzers import RootCauseAnalyzer
from app.services.analysis.models import AnalysisTask, ComputationType
from app.agent.semantic.models import AnalysisOperation


# ─── Test 1: Hypothesis Creation & Structured Generation ───

def test_1_hypothesis_creation_and_generation():
    """Test 1: HypothesisManager creates structured candidate hypotheses for root-cause queries."""
    hypotheses = HypothesisManager.generate_candidate_hypotheses(
        question="Why did revenue drop in Q3?",
        metrics=["revenue"],
        dimensions=["category", "region"],
    )

    assert len(hypotheses) >= 3
    h_ids = [h.hypothesis_id for h in hypotheses]
    assert "h_volume" in h_ids
    assert "h_price_aov" in h_ids
    assert "h_segment_category" in h_ids

    for h in hypotheses:
        assert h.status == HypothesisStatus.PROPOSED
        assert len(h.required_evidence) > 0
        assert h.confidence == 0.0


# ─── Test 2: Hypothesis Support ───

def test_2_hypothesis_support():
    """Test 2: Verified negative volume evidence supports the volume decline hypothesis."""
    hyp = Hypothesis(
        hypothesis_id="h_volume",
        statement="Revenue decline is primarily volume-driven (order count drop).",
        status=HypothesisStatus.PROPOSED,
    )
    evidence = [
        EvidenceItem(
            evidence_id="ev_orders",
            source_query_id="q_1",
            statement="Total order_count decreased by 25% from 4,000 to 3,000",
            metric="order_count",
            value={"delta": -1000, "pct_change": -25.0},
            evidence_type=EvidenceType.COMPARISON,
        )
    ]

    evaluated = HypothesisManager.evaluate_single_hypothesis(hyp, evidence)
    assert evaluated.status == HypothesisStatus.SUPPORTED
    assert evaluated.confidence >= 0.85
    assert len(evaluated.supporting_evidence) == 1
    assert "order_count decreased" in evaluated.supporting_evidence[0]
    assert len(evaluated.contradicting_evidence) == 0


# ─── Test 3: Hypothesis Rejection ───

def test_3_hypothesis_rejection():
    """Test 3: Evidence showing price/AOV was stable or increased rejects the price decline hypothesis."""
    hyp = Hypothesis(
        hypothesis_id="h_price_aov",
        statement="Revenue decline is primarily realization-driven (AOV drop).",
        status=HypothesisStatus.PROPOSED,
    )
    evidence = [
        EvidenceItem(
            evidence_id="ev_aov",
            source_query_id="q_2",
            statement="Average order value grew by 5% from 100 to 105",
            metric="avg_order_value",
            value={"delta": 5.0, "pct_change": 5.0},
            evidence_type=EvidenceType.COMPARISON,
        )
    ]

    evaluated = HypothesisManager.evaluate_single_hypothesis(hyp, evidence)
    assert evaluated.status == HypothesisStatus.REJECTED
    assert evaluated.confidence >= 0.80
    assert len(evaluated.contradicting_evidence) == 1
    assert len(evaluated.supporting_evidence) == 0


# ─── Test 4: Contradiction & Mixed Evidence ───

def test_4_contradiction_and_mixed_evidence():
    """Test 4: Mixed supporting and contradicting evidence results in INCONCLUSIVE status."""
    hyp = Hypothesis(
        hypothesis_id="h_volume",
        statement="Revenue decline is volume-driven.",
        status=HypothesisStatus.PROPOSED,
    )
    evidence = [
        EvidenceItem(
            evidence_id="ev_1",
            statement="Orders fell in Region A",
            metric="orders",
            value=-50,
        ),
        EvidenceItem(
            evidence_id="ev_2",
            statement="Orders grew in Region B",
            metric="orders",
            value=80,
        ),
    ]

    evaluated = HypothesisManager.evaluate_single_hypothesis(hyp, evidence)
    assert evaluated.status == HypothesisStatus.INCONCLUSIVE
    assert len(evaluated.supporting_evidence) == 1
    assert len(evaluated.contradicting_evidence) == 1
    assert evaluated.confidence == 0.50


# ─── Test 5: Incomplete Evidence ───

def test_5_incomplete_evidence():
    """Test 5: Unrelated evidence leaves hypothesis as INCONCLUSIVE with 0 confidence."""
    hyp = Hypothesis(
        hypothesis_id="h_churn",
        statement="Customer churn increased by 10%",
        status=HypothesisStatus.PROPOSED,
    )
    evidence = [
        EvidenceItem(
            evidence_id="ev_tax",
            statement="Tax rate remained constant at 15%",
            metric="tax_rate",
            value=0.15,
        )
    ]

    evaluated = HypothesisManager.evaluate_single_hypothesis(hyp, evidence)
    assert evaluated.status == HypothesisStatus.INCONCLUSIVE
    assert evaluated.confidence == 0.0
    assert len(evaluated.supporting_evidence) == 0
    assert len(evaluated.contradicting_evidence) == 0


# ─── Test 6: Deterministic Numerical Contribution Calculation ───

def test_6_deterministic_numerical_contribution():
    """Test 6: Pure Python calculates baseline, current, delta, and exact percentage share of decline."""
    rows = [
        {"period": "2024", "category": "Electronics", "revenue": 1000.0},
        {"period": "2024", "category": "Furniture", "revenue": 500.0},
        {"period": "2025", "category": "Electronics", "revenue": 600.0},  # -400 (-40%)
        {"period": "2025", "category": "Furniture", "revenue": 400.0},    # -100 (-20%)
    ]
    # Total negative drop = -400 + -100 = -500
    # Electronics share = -400 / -500 = 80.0%
    # Furniture share = -100 / -500 = 20.0%

    contributions = HypothesisManager.calculate_segment_contributions(
        rows=rows,
        dimension_col="category",
        metric_col="revenue",
        time_col="period",
    )

    assert len(contributions) == 2
    elec = next(c for c in contributions if c.category == "Electronics")
    assert elec.baseline_value == 1000.0
    assert elec.current_value == 600.0
    assert elec.delta == -400.0
    assert elec.growth_pct == -40.0
    assert elec.contribution_to_decline_pct == 80.0
    assert elec.is_primary_driver is True

    furn = next(c for c in contributions if c.category == "Furniture")
    assert furn.baseline_value == 500.0
    assert furn.current_value == 400.0
    assert furn.delta == -100.0
    assert furn.growth_pct == -20.0
    assert furn.contribution_to_decline_pct == 20.0
    assert furn.is_primary_driver is False


# ─── Test 7: Multiple Root Causes ───

def test_7_multiple_primary_drivers():
    """Test 7: When multiple segments have large drops, both are identified as primary drivers."""
    rows = [
        {"period": "2024", "category": "Apparel", "revenue": 1000.0},
        {"period": "2024", "category": "Footwear", "revenue": 1000.0},
        {"period": "2025", "category": "Apparel", "revenue": 500.0},     # -500 (50%)
        {"period": "2025", "category": "Footwear", "revenue": 500.0},    # -500 (50%)
    ]

    contributions = HypothesisManager.calculate_segment_contributions(
        rows=rows,
        dimension_col="category",
        metric_col="revenue",
        time_col="period",
    )

    primary_drivers = [c for c in contributions if c.is_primary_driver]
    assert len(primary_drivers) == 2
    assert {c.category for c in primary_drivers} == {"Apparel", "Footwear"}
    for c in primary_drivers:
        assert c.contribution_to_decline_pct == 50.0


# ─── Test 8: No Root Cause Identifiable (All Positive/Flat) ───

def test_8_no_root_cause_identifiable_when_growing():
    """Test 8: When all segments grew, no negative contributors exist and findings state inconclusive."""
    rows = [
        {"period": "2024", "category": "Tech", "revenue": 100.0},
        {"period": "2025", "category": "Tech", "revenue": 150.0},  # +50
    ]

    contributions = HypothesisManager.calculate_segment_contributions(
        rows=rows,
        dimension_col="category",
        metric_col="revenue",
        time_col="period",
    )

    primary_drivers = [c for c in contributions if c.is_primary_driver]
    assert len(primary_drivers) == 0

    findings = HypothesisManager.synthesize_root_cause_findings(
        hypotheses=[],
        contributions=contributions,
    )
    assert any("لم يتم التوصل إلى سبب جذري" in f for f in findings)


# ─── Test 9: Deterministic Hypothesis Ranking ───

def test_9_deterministic_hypothesis_ranking():
    """Test 9: SUPPORTED hypotheses rank before INCONCLUSIVE and REJECTED hypotheses."""
    h_supp = Hypothesis(hypothesis_id="h_1", statement="H1", status=HypothesisStatus.SUPPORTED, confidence=0.9, supporting_evidence=["E1"])
    h_inconc = Hypothesis(hypothesis_id="h_2", statement="H2", status=HypothesisStatus.INCONCLUSIVE, confidence=0.5, supporting_evidence=["E2"])
    h_prop = Hypothesis(hypothesis_id="h_3", statement="H3", status=HypothesisStatus.PROPOSED, confidence=0.0)
    h_rej = Hypothesis(hypothesis_id="h_4", statement="H4", status=HypothesisStatus.REJECTED, confidence=0.8)

    ranked = HypothesisManager.rank_hypotheses([h_rej, h_prop, h_supp, h_inconc])
    assert [h.hypothesis_id for h in ranked] == ["h_1", "h_2", "h_3", "h_4"]


# ─── Test 10: RootCauseAnalyzer Integration ───

def test_10_root_cause_analyzer_execution():
    """Test 10: RootCauseAnalyzer integrates HypothesisManager and generates structured contributions."""
    analyzer = RootCauseAnalyzer()
    task = AnalysisTask(
        task_id="rc_task",
        name="Investigate Product Drop",
        operation=AnalysisOperation.ROOT_CAUSE,
        computation_type=ComputationType.SEGMENT_RANKING,
    )
    rows = [
        {"period": "2024", "product": "Widget A", "sales": 200.0},
        {"period": "2025", "product": "Widget A", "sales": 100.0},
    ]

    res = analyzer.execute(task, rows=rows, numeric_cols=["sales"], dimension_cols=["product", "period"])
    assert res.task_id == "rc_task"
    assert "segment_contributions" in res.computed_metrics
    conts = res.computed_metrics["segment_contributions"]
    assert len(conts) == 1
    assert conts[0]["category"] == "Widget A"
    assert conts[0]["delta"] == -100.0
    assert len(res.findings) > 0


# ─── Test 11: InvestigationState Hypothesis Lifecycle ───

def test_11_investigation_state_hypothesis_lifecycle():
    """Test 11: InvestigationEngine updates active hypotheses on recording execution results."""
    plan = InvestigationPlan(
        question="Why did sales drop?",
        query_tasks=[QueryTask(query_id="q_1", purpose="Q1", sub_question="Order volume drop")],
    )
    state = InvestigationEngine.initialize_investigation(plan)
    state.add_hypothesis(
        Hypothesis(
            hypothesis_id="h_volume",
            statement="Sales drop is volume-driven.",
            status=HypothesisStatus.PROPOSED,
        )
    )

    t1 = InvestigationEngine.select_next_task(state)
    InvestigationEngine.record_execution_result(
        state,
        t1,
        sql="SELECT -50 AS order_count",
        rows=[{"order_count": -50.0}],
    )

    assert len(state.active_hypotheses) == 1
    assert state.active_hypotheses[0].status == HypothesisStatus.SUPPORTED
    assert state.tested_hypotheses["h_volume"] is True
