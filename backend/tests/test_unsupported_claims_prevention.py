"""Unit tests for unsupported claims prevention rule."""
import pytest
from app.services.sql.result_verifier import ResultVerifier, DeterministicFact
from app.services.analysis.models import AnalysisResult


def test_unsupported_speculative_claim_prevention():
    verifier = ResultVerifier()

    rows = [
        {"region": "Cairo", "sales": 390000.0},
        {"region": "Alex", "sales": 250000.0},
    ]

    # Report makes an unsupported causal assertion ("السبب هو ضعف التسويق والمنافسة")
    unsupported_report = "انخفضت المبيعات في الربع الأخير. السبب هو ضعف التسويق والمنافسين في السوق."

    constrained, evaluations, confidence = verifier.verify_and_constrain_prose(
        unsupported_report,
        rows=rows,
    )

    # Must detect the unsupported claim
    unsupported_evals = [e for e in evaluations if e.status == "UNSUPPORTED_CLAIM"]
    assert len(unsupported_evals) >= 1
    assert not unsupported_evals[0].is_verified
    assert unsupported_evals[0].confidence == 0.0
    assert "unsupported_claim" in unsupported_evals[0].evidence_source
    assert "*(unsupported claim)*" in constrained


def test_supported_claim_with_database_evidence():
    verifier = ResultVerifier()

    rows = [
        {"region": "Cairo", "sales": 390000.0},
    ]

    analysis_res = AnalysisResult(
        analysis_type="root_cause",
        goal="Decline analysis",
        findings=["Cairo sales is 390000.0"],
        metrics={"cairo_sales": 390000.0},
        evidence=["Cairo sales reached 390,000"],
    )

    report = "Cairo sales reached 390,000 in the latest quarter."

    constrained, evaluations, confidence = verifier.verify_and_constrain_prose(
        report,
        rows=rows,
        analytics_result=analysis_res,
    )

    verified_evals = [e for e in evaluations if e.status == "VERIFIED"]
    assert len(verified_evals) >= 1
    assert verified_evals[0].is_verified
