"""Ambiguity Resolver (P1 Feature).

Detects ambiguous entity, table, or column references and provides either:
1. Automated disambiguation with explicit logged evidence and score margins.
2. Structured clarification questions when multiple candidates have equal confidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Dict, Optional
from loguru import logger


@dataclass
class AmbiguityCandidate:
    name: str
    entity_type: str  # "table" or "column"
    score: float
    reason: str
    description: Optional[str] = None


@dataclass
class AmbiguityResolution:
    is_ambiguous: bool = False
    chosen_candidate: Optional[str] = None
    candidates: List[AmbiguityCandidate] = field(default_factory=list)
    clarification_prompt: Optional[str] = None
    evidence: str = ""


class AmbiguityResolver:
    """Evaluates candidate matches to detect and resolve semantic ambiguity."""

    def resolve_table_ambiguity(
        self,
        question: str,
        candidates: List[Dict[str, Any]],
        threshold_margin: float = 0.15,
    ) -> AmbiguityResolution:
        """
        If top candidates have similarity scores within `threshold_margin`,
        flags ambiguity and builds a clarification prompt.
        """
        if not candidates:
            return AmbiguityResolution(is_ambiguous=False)

        sorted_cands = sorted(candidates, key=lambda c: c.get("score", 0.0), reverse=True)
        amb_candidates = [
            AmbiguityCandidate(
                name=c["name"],
                entity_type="table",
                score=c.get("score", 0.0),
                reason=c.get("reason", "Lexical/Semantic match"),
                description=c.get("description"),
            )
            for c in sorted_cands
        ]

        if len(sorted_cands) < 2:
            return AmbiguityResolution(
                is_ambiguous=False,
                chosen_candidate=sorted_cands[0]["name"],
                candidates=amb_candidates,
                evidence=f"Single dominant candidate '{sorted_cands[0]['name']}'.",
            )

        top_score = sorted_cands[0].get("score", 0.0)
        second_score = sorted_cands[1].get("score", 0.0)

        # Ambiguous if top two candidates have very close relevance scores
        if (top_score - second_score) < threshold_margin and top_score > 0.3:
            cand_names = [c["name"] for c in sorted_cands[:3]]
            options_str = " or ".join(f"'{c}'" for c in cand_names)
            clarification = f"Your question could refer to multiple related tables ({options_str}). Which one would you like to inspect?"

            return AmbiguityResolution(
                is_ambiguous=True,
                chosen_candidate=sorted_cands[0]["name"],  # Default fallback
                candidates=amb_candidates[:3],
                clarification_prompt=clarification,
                evidence=f"Ambiguity detected between '{sorted_cands[0]['name']}' (score {top_score:.2f}) and '{sorted_cands[1]['name']}' (score {second_score:.2f}).",
            )

        return AmbiguityResolution(
            is_ambiguous=False,
            chosen_candidate=sorted_cands[0]["name"],
            candidates=amb_candidates,
            evidence=f"Dominant candidate '{sorted_cands[0]['name']}' selected (score {top_score:.2f} vs {second_score:.2f}).",
        )


# Global singleton instance
ambiguity_resolver = AmbiguityResolver()
