import pytest
from types import SimpleNamespace
from app.sql.result_verifier import ResultVerifier, DeterministicFact, ClaimEvaluation
from app.services.feedback_service import FeedbackService
from app.database.system_store import SystemStore
from app.services.report_service import ReportService


def test_deterministic_fact_generation():
    """Test generating 100% verified facts from execution results."""
    verifier = ResultVerifier()

    # 1. Empty rows
    empty_facts = verifier.generate_deterministic_facts([])
    assert len(empty_facts) == 1
    assert empty_facts[0].fact_type == "empty_state"
    assert empty_facts[0].confidence == 1.0

    # 2. Scalar result
    scalar_rows = [{"total_revenue": 45200.50}]
    scalar_facts = verifier.generate_deterministic_facts(scalar_rows)
    assert any(f.fact_type == "scalar" and f.source_value == 45200.50 for f in scalar_facts)

    # 3. Multi-row results only aggregate the metric and operation the query asks for.
    rows = [
        {"department": "Engineering", "salary": 120000, "bonus": 15000},
        {"department": "Sales", "salary": 80000, "bonus": 25000},
        {"department": "Marketing", "salary": 90000, "bonus": 10000},
    ]
    facts = verifier.generate_deterministic_facts(
        rows,
        query_spec=SimpleNamespace(aggregations=["AVG"], metrics=["salary"]),
        question="What is the average salary?",
    )
    assert any(f.fact_type == "metric_aggregation" and "Average salary" in f.statement for f in facts)
    assert all(f.source_column != "bonus" for f in facts)
    assert all(f.source_column != "department" for f in facts)


def test_deterministic_facts_for_ranking_include_only_ranked_entities_and_metric():
    verifier = ResultVerifier()
    rows = [
        {"customer_id": 7, "customer_name": "Acme", "revenue": 900.0},
        {"customer_id": 3, "customer_name": "Beta", "revenue": 750.0},
    ]

    facts = verifier.generate_deterministic_facts(
        rows,
        query_spec=SimpleNamespace(expected_output="ranking", aggregations=[], metrics=["revenue"]),
        question="Top 5 customers by revenue",
        sql="SELECT customer_id, customer_name, revenue FROM customers ORDER BY revenue DESC LIMIT 5",
    )

    assert [fact.fact_type for fact in facts] == ["ranked_entity", "ranked_entity"]
    assert [fact.source_value["entity"] for fact in facts] == ["Acme", "Beta"]
    assert all(fact.source_column == "revenue" for fact in facts)


def test_verify_and_constrain_prose_grounded_vs_hallucinated():
    """Test verifying narrative claims against ground truth and constraining hallucinated prose."""
    verifier = ResultVerifier()

    rows = [
        {"product": "Laptop", "units_sold": 150, "revenue": 150000.0},
        {"product": "Phone", "units_sold": 300, "revenue": 180000.0},
    ]
    facts = verifier.generate_deterministic_facts(rows)

    # 1. Grounded narrative (all figures exist in data or facts)
    grounded_text = "Total revenue reached $330,000 across 2 products. Phone had 300 units sold."
    constrained, evals, conf = verifier.verify_and_constrain_prose(grounded_text, rows, facts=facts)
    assert conf == 1.0
    assert all(e.is_verified for e in evals)
    assert "unverified claim" not in constrained
    phone_claim = next(e for e in evals if "Phone" in e.statement)
    assert phone_claim.metric == "units_sold"
    assert phone_claim.entity == "Phone"
    assert phone_claim.operation == "value"
    assert phone_claim.evidence["matches"][0]["row"] == 1
    assert phone_claim.evidence["matches"][0]["column"] == "units_sold"

    # 2. Hallucinated narrative (contains fabricated number 999,999)
    hallucinated_text = "Total revenue was $330,000. However, customer churn was 999,999 users."
    constrained, evals, conf = verifier.verify_and_constrain_prose(hallucinated_text, rows, facts=facts)
    assert conf < 1.0
    assert any(not e.is_verified for e in evals)
    assert "unverified claim" in constrained


def test_same_number_in_an_unrelated_metric_is_not_verified():
    """A matching value alone cannot prove a different semantic claim."""
    verifier = ResultVerifier()
    rows = [{"product": "Phone", "units_sold": 300, "churn": 12}]

    constrained, evaluations, confidence = verifier.verify_and_constrain_prose(
        "Phone churn was 300.", rows
    )

    assert confidence == 0.0
    assert evaluations[0].status == "UNVERIFIED"
    assert "unverified claim" in constrained


@pytest.mark.asyncio
async def test_report_uses_facts_from_full_result_after_llm_truncation():
    """A 200-row display sample must not change totals over 250 raw rows."""
    full_rows = [{"amount": value} for value in range(1, 251)]
    sample_rows = full_rows[:200]
    facts = ResultVerifier().generate_deterministic_facts(full_rows, question="What is total amount?")

    report = await ReportService().generate_report(
        question="What is total amount?",
        sql="SELECT amount FROM sales",
        results=sample_rows,
        require_verification=False,
        verified_facts=facts,
        total_result_rows=len(full_rows),
    )

    assert "250" in report
    assert "31,375.00" in report

    with pytest.raises(ValueError, match="Truncated report rows require verified_facts"):
        await ReportService().generate_report(
            question="What is total amount?",
            sql="SELECT amount FROM sales",
            results=sample_rows,
            require_verification=False,
            total_result_rows=len(full_rows),
        )


def test_claim_feedback_recording_and_retrieval(tmp_path, monkeypatch):
    """Test recording user feedback and corrections on specific claims."""
    store = SystemStore(db_url_or_path=str(tmp_path / "claim_fb.db"))
    monkeypatch.setattr("app.database.system_store.system_store", store)

    service = FeedbackService()

    claim_id = "claim_rev_123"
    question = "What is our quarterly revenue?"
    statement = "Total revenue is $45,200.00"

    # Record feedback (positive rating 5)
    fb1 = service.record_claim_feedback(
        claim_id=claim_id,
        statement=statement,
        user_rating=5,
        question=question,
        user_id="user_admin",
    )
    assert fb1["feedback_id"] is not None
    assert fb1["user_rating"] == 5

    # Record correction feedback (rating 1 with correction)
    fb2 = service.record_claim_feedback(
        claim_id=claim_id,
        statement=statement,
        user_rating=1,
        question=question,
        user_correction="Revenue was actually $48,000 due to delayed invoices.",
        user_id="user_cfo",
    )
    assert fb2["user_rating"] == 1
    assert "delayed invoices" in fb2["user_correction"]

    # Retrieve feedback
    history = service.get_claim_feedback(claim_id=claim_id)
    assert len(history) == 2
    assert any(h["user_rating"] == 5 for h in history)
    assert any(h["user_rating"] == 1 for h in history)
