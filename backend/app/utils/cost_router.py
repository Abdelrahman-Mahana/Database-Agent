"""Adaptive cost-tier routing (Phase 4 of the rebuild plan).

Previously, self-consistency (multiple parallel SQL candidates + majority
voting) was a single global on/off switch (`ENABLE_SELF_CONSISTENCY`): either
every question pays for N candidates, or no question ever gets the extra
reliability. Neither is right — a simple "how many customers" lookup gains
almost nothing from voting, while an ambiguous comparison/trend question
benefits a lot.

This module makes the decision per-question instead of globally, based on
signals that are already computed for free (analysis type, question length/
ambiguity markers) — no extra LLM call needed to decide.
"""
from __future__ import annotations

from app.core.config import settings
from app.utils.text_processor import AnalysisType, COMPLEX_ANALYSIS_TYPES

# Analysis types where a single wrong JOIN/GROUP BY choice is likely and
# costly to get wrong (ambiguous phrasing, multiple valid interpretations) —
# these are worth paying for extra candidates even if the global switch is
# conservatively left off by default.
_VOTING_WORTHY_TYPES = COMPLEX_ANALYSIS_TYPES | {AnalysisType.RANKING}

# Heuristic ambiguity markers: questions with these tend to have multiple
# plausible SQL interpretations (which join, which aggregation grain).
_AMBIGUITY_MARKERS_EN = ("best", "top", "most", "compare", "vs", "versus", "trend", "why", "correlat")
_AMBIGUITY_MARKERS_AR = ("أفضل", "أكثر", "قارن", "مقارنة", "اتجاه", "لماذا", "علاقة")


def should_use_self_consistency(question: str, analysis_type: AnalysisType) -> bool:
    """Decide whether this specific question should get self-consistency voting.

    Global settings still act as hard bounds:
      - if ENABLE_SELF_CONSISTENCY=false AND the question isn't flagged as
        voting-worthy, we skip it (safe default, no surprise cost increase).
      - if ENABLE_SELF_CONSISTENCY=true, voting-worthy/ambiguous questions
        still get it, but simple lookup/count questions are downgraded to a
        single candidate to avoid paying 3x for "how many rows in Orders".
    """
    if settings.sql_candidates <= 1:
        return False

    is_voting_worthy_type = analysis_type in _VOTING_WORTHY_TYPES
    q_lower = (question or "").lower()
    has_ambiguity_marker = any(m in q_lower for m in _AMBIGUITY_MARKERS_EN) or any(
        m in question for m in _AMBIGUITY_MARKERS_AR
    )

    if settings.enable_self_consistency:
        # Global opt-in: still skip the cheap/unambiguous majority of questions.
        if analysis_type in (AnalysisType.LOOKUP, AnalysisType.COUNT) and not has_ambiguity_marker:
            return False
        return True

    # Global opt-out: only pay for it when the question type is genuinely
    # risky to get wrong on the first try.
    return is_voting_worthy_type or has_ambiguity_marker


def choose_sql_generation_tier(question: str, analysis_type: AnalysisType, confidence: float = 1.0) -> str:
    """Rebuild Plan — Phase 6: real model-tier routing.

    Returns "fast" or "primary" for the SQL-GENERATION call specifically.
    Deliberately reuses the exact same signals this module already computes
    for the self-consistency decision above (analysis_type classification +
    ambiguity markers + the understanding layer's own confidence) instead of
    inventing a second, separate heuristic - the roadmap's explicit ask.

    A question only gets downgraded to the fast/cheap model when ALL of:
      - it's a simple type (lookup/count) - not ranking/comparison/trend/
        root_cause/multi_step, which is exactly `_VOTING_WORTHY_TYPES` above
        (same "is this actually simple" signal driving BOTH decisions).
      - it has no ambiguity marker.
      - the understanding layer was confident about it (>= threshold). A
        low-confidence LOOKUP is still routed to "primary" - if the
        understanding itself is unsure, don't also cheap out on generation.
    Never affects self-consistency-eligible questions - those are already
    the ones this function routes to "primary" anyway (voting on the cheap
    model would undermine the whole point of voting).
    """
    if not settings.enable_model_routing:
        return "primary"

    is_simple_type = analysis_type in (AnalysisType.LOOKUP, AnalysisType.COUNT)
    q_lower = (question or "").lower()
    has_ambiguity_marker = any(m in q_lower for m in _AMBIGUITY_MARKERS_EN) or any(
        m in question for m in _AMBIGUITY_MARKERS_AR
    )
    is_confident = confidence >= settings.model_routing_min_confidence

    if is_simple_type and not has_ambiguity_marker and is_confident:
        return "fast"
    return "primary"
