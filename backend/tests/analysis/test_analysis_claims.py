"""Tests for Analytical Claim Verification and Hallucination Prevention."""
import pytest
from app.services.sql.result_verifier import ResultVerifier
from app.services.analysis.models import AnalysisResult


def test_claims_verifier_blocks_unsupported_causation():
    verifier = ResultVerifier()
    rows = [{"branch": "Dokki", "revenue": 100000.0}]

    # Narrative has an unsupported causal claim ("السبب هو سوء الأحوال الجوية والمنافسين")
    prose = "إجمالي الإيرادات هو 100,000. السبب هو سوء الأحوال الجوية والمنافسين."

    constrained, evaluations, conf = verifier.verify_and_constrain_prose(
        prose,
        rows=rows,
    )

    unsupported = [e for e in evaluations if e.status == "UNSUPPORTED_CLAIM"]
    assert len(unsupported) >= 1
    assert unsupported[0].confidence == 0.0
    assert "unsupported_claim" in unsupported[0].evidence_source
    assert "*(unsupported claim)*" in constrained


def test_claims_verifier_allows_grounded_claims():
    verifier = ResultVerifier()
    rows = [{"branch": "Dokki", "revenue": 100000.0}]

    analysis_res = AnalysisResult(
        analysis_type="metric",
        goal="Branch revenue",
        findings=["Dokki revenue is 100,000"],
        metrics={"revenue": 100000.0},
        evidence=["Dokki branch = 100K"],
    )

    prose = "Dokki branch generated 100,000 in revenue."

    constrained, evaluations, conf = verifier.verify_and_constrain_prose(
        prose,
        rows=rows,
        analytics_result=analysis_res,
    )

    verified = [e for e in evaluations if e.status == "VERIFIED"]
    assert len(verified) >= 1
    assert verified[0].is_verified
