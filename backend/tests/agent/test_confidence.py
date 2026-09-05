import pytest
from app.agent.schema_grounding.confidence import grounding_confidence

class MockGrounded:
    def __init__(self, evidence=None, fallback_used=False, selected_tables=None, selected_columns=None):
        self.evidence = evidence or {}
        self.fallback_used = fallback_used
        self.selected_tables = selected_tables or []
        self.selected_columns = selected_columns or {}

class MockQuerySpec:
    def __init__(self, requires_clarification=False, ambiguity_candidates=None):
        self.requires_clarification = requires_clarification
        self.ambiguity_candidates = ambiguity_candidates or []

def test_grounding_confidence_perfect():
    """Test confidence scoring when all evidence signals are present."""
    grounded = MockGrounded(
        evidence={
            "exact_entity_match": True,
            "glossary_match": True,
            "embedding_relevance": True,
            "column_relevance": True,
            "join_path_confidence": True,
        }
    )
    score, details = grounding_confidence(grounded)
    assert score == 1.0
    assert all(details["signals"].values())
    assert details["fallback_penalty"] == 0.0

def test_grounding_confidence_fallback_penalty():
    """Test confidence scoring when fallback is used."""
    grounded = MockGrounded(
        evidence={
            "exact_entity_match": True,
        },
        fallback_used=True
    )
    score, details = grounding_confidence(grounded)
    # exact_entity_match is 0.35, penalty is 0.30
    assert score == 0.05
    assert details["fallback_used"] is True
    assert details["fallback_penalty"] == 0.30

def test_grounding_confidence_ambiguity_penalty():
    """Test confidence scoring when query is ambiguous."""
    grounded = MockGrounded(
        evidence={
            "exact_entity_match": True,
        }
    )
    spec = MockQuerySpec(requires_clarification=True)
    score, details = grounding_confidence(grounded, query_spec=spec)
    # exact_entity_match is 0.35, penalty is 0.20
    assert score == 0.15
    assert details["ambiguity_detected"] is True
    assert details["ambiguity_penalty"] == 0.20

def test_grounding_confidence_no_evidence_but_selected():
    """Test implicit confidence assignment when tables are selected without explicit evidence."""
    grounded = MockGrounded(selected_tables=["users", "orders"])
    score, details = grounding_confidence(grounded)
    assert score == 0.65
    
    grounded_cols = MockGrounded(selected_tables=["users"], selected_columns={"users": ["id"]})
    score2, details2 = grounding_confidence(grounded_cols)
    assert score2 == 0.75
