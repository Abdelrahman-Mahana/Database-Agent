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

from app.config.settings import settings
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


def should_use_self_consistency(
    question: str,
    analysis_type: AnalysisType,
    schema_token_estimate: int = 0,
) -> bool:
    """Decide whether this specific question should get self-consistency voting."""
    if settings.sql_candidates <= 1:
        return False

    max_sc_tokens = getattr(settings, "self_consistency_max_schema_tokens", 4000)
    if schema_token_estimate > max_sc_tokens:
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



def choose_sql_generation_tier(
    question: str,
    analysis_type: AnalysisType,
    confidence: float = 1.0,
    grounded_table_count: int = 1,
    has_grouping: bool = False,
) -> str:
    """Rebuild Plan — Phase 6 & Phase 6.4: real model-tier routing.

    Returns "fast" or "primary" for the SQL-GENERATION call specifically.

    A question is allowed to use the fast model ONLY when ALL of:
      - analysis_type is LOOKUP or COUNT
      - confidence >= settings.model_routing_min_confidence
      - no ambiguity marker exists
      - grounded_table_count == 1 (single-table queries only; multi-table JOINs require primary)
      - has_grouping is False (queries requiring GROUP BY require primary)
    Otherwise routes to "primary".
    """
    if not settings.enable_model_routing:
        return "primary"

    is_simple_type = analysis_type in (AnalysisType.LOOKUP, AnalysisType.COUNT)
    q_lower = (question or "").lower()
    has_ambiguity_marker = any(m in q_lower for m in _AMBIGUITY_MARKERS_EN) or any(
        m in question for m in _AMBIGUITY_MARKERS_AR
    )
    is_confident = confidence >= settings.model_routing_min_confidence
    is_single_table = grounded_table_count == 1
    no_grouping = not has_grouping

    if is_simple_type and not has_ambiguity_marker and is_confident and is_single_table and no_grouping:
        return "fast"
    return "primary"

