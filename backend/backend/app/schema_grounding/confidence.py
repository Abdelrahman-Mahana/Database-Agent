"""Evidence-based confidence scoring for schema grounding."""
from __future__ import annotations

from typing import Any


_WEIGHTS = {
    "exact_entity_match": 0.35,
    "glossary_match": 0.20,
    "embedding_relevance": 0.20,
    "column_relevance": 0.15,
    "join_path_confidence": 0.10,
}


def grounding_confidence(grounded: Any, query_spec: Any = None) -> tuple[float, dict[str, Any]]:
    """Score only observed relevance signals; centrality fallback carries a penalty."""
    evidence = dict(getattr(grounded, "evidence", {}) or {})
    signals = {name: bool(evidence.get(name, False)) for name in _WEIGHTS}
    score = sum(weight for name, weight in _WEIGHTS.items() if signals[name])

    fallback_used = bool(getattr(grounded, "fallback_used", False))
    ambiguous = bool(
        getattr(query_spec, "requires_clarification", False)
        or getattr(query_spec, "ambiguity_candidates", [])
    )
    if fallback_used:
        score -= 0.30
    if ambiguous:
        score -= 0.20

    score = round(max(0.0, min(1.0, score)), 2)
    return score, {
        "signals": signals,
        "fallback_used": fallback_used,
        "ambiguity_detected": ambiguous,
        "fallback_penalty": 0.30 if fallback_used else 0.0,
        "ambiguity_penalty": 0.20 if ambiguous else 0.0,
    }
