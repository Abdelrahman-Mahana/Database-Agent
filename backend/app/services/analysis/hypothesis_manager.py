"""Controlled Hypothesis Investigation & Evidence-Driven Root Cause Manager (Phase 6).

Responsible for:
1. Hypothesis registration and structured generation for investigative questions.
2. Grounded deterministic hypothesis testing against accumulated EvidenceItems.
3. Pure Python deterministic segment contribution and waterfall calculations.
4. Deterministic hypothesis ranking (supported, inconclusive, rejected).
5. Evidence-based root-cause synthesis without LLM mathematical hallucination.
"""
from dataclasses import dataclass, field
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.analysis.investigation_models import (
    EvidenceItem,
    EvidenceType,
    Hypothesis,
    HypothesisStatus,
    InvestigationState,
    InvestigationStatus,
)

logger = logging.getLogger(__name__)


# ─── Contribution Analysis Record ───

@dataclass
class SegmentContribution:
    """Quantitative contribution of a segment/category to an overall metric change."""
    dimension: str
    category: str
    baseline_value: float
    current_value: float
    delta: float
    growth_pct: float
    contribution_to_decline_pct: float
    is_primary_driver: bool = False


# ─── Hypothesis Manager ───

class HypothesisManager:
    """Manages hypothesis lifecycle, evidence testing, contribution analysis, and deterministic ranking."""

    @classmethod
    def generate_candidate_hypotheses(
        cls,
        question: str,
        metrics: Optional[List[str]] = None,
        dimensions: Optional[List[str]] = None,
    ) -> List[Hypothesis]:
        """Generate structured candidate hypotheses for root-cause and diagnostic questions."""
        q_lower = question.lower()
        metrics = metrics or ["revenue"]
        primary_metric = metrics[0] if metrics else "performance"
        dimensions = dimensions or ["product", "region", "channel"]

        hypotheses: List[Hypothesis] = []

        # 1. Volume vs Realization Hypotheses
        hypotheses.append(
            Hypothesis(
                hypothesis_id="h_volume",
                statement=f"{primary_metric.capitalize()} decline is primarily volume-driven (decrease in orders/transactions).",
                required_evidence=["order count change", "transaction volume change"],
                status=HypothesisStatus.PROPOSED,
            )
        )
        hypotheses.append(
            Hypothesis(
                hypothesis_id="h_price_aov",
                statement=f"{primary_metric.capitalize()} decline is primarily realization-driven (decrease in average order value or unit price).",
                required_evidence=["average order value change", "unit price change"],
                status=HypothesisStatus.PROPOSED,
            )
        )

        # 2. Dimensional Concentration Hypotheses
        for dim in dimensions[:2]:
            hypotheses.append(
                Hypothesis(
                    hypothesis_id=f"h_segment_{dim}",
                    statement=f"{primary_metric.capitalize()} decline is concentrated in specific {dim} segments.",
                    required_evidence=[f"{dim} contribution to decline", f"{dim} segment growth rates"],
                    status=HypothesisStatus.PROPOSED,
                )
            )

        return hypotheses

    @classmethod
    def evaluate_hypotheses(
        cls,
        hypotheses: List[Hypothesis],
        evidence: List[EvidenceItem],
        state: Optional[InvestigationState] = None,
    ) -> List[Hypothesis]:
        """Deterministically test each hypothesis against accumulated evidence items."""
        evaluated: List[Hypothesis] = []

        for hyp in hypotheses:
            updated = cls.evaluate_single_hypothesis(hyp, evidence, state)
            evaluated.append(updated)

        return evaluated

    @classmethod
    def evaluate_single_hypothesis(
        cls,
        hypothesis: Hypothesis,
        evidence: List[EvidenceItem],
        state: Optional[InvestigationState] = None,
    ) -> Hypothesis:
        """Evaluate a single hypothesis against all available evidence items."""
        supporting: List[str] = []
        contradicting: List[str] = []
        h_id = hypothesis.hypothesis_id.lower()
        stmt_lower = hypothesis.statement.lower()

        for ev in evidence:
            ev_stmt = ev.statement.lower()
            ev_val = ev.value

            # Evaluate Volume Hypothesis
            if "volume" in h_id or "volume-driven" in stmt_lower:
                if any(k in ev_stmt for k in ("order_count", "orders", "volume", "transaction", "count")):
                    # Check if volume declined
                    if isinstance(ev_val, (int, float)) and ev_val < 0:
                        supporting.append(ev.statement)
                    elif isinstance(ev_val, dict) and ev_val.get("delta", 0) < 0:
                        supporting.append(ev.statement)
                    elif any(w in ev_stmt for w in ("lower", "decreased", "drop", "fell", "declined")):
                        supporting.append(ev.statement)
                    elif any(w in ev_stmt for w in ("higher", "increased", "grew")):
                        contradicting.append(ev.statement)

            # Evaluate Price / AOV Hypothesis
            elif "price" in h_id or "aov" in h_id or "realization" in stmt_lower:
                if any(k in ev_stmt for k in ("aov", "avg_order", "average order", "unit_price", "price")):
                    if isinstance(ev_val, (int, float)) and ev_val < 0:
                        supporting.append(ev.statement)
                    elif isinstance(ev_val, dict) and ev_val.get("delta", 0) < 0:
                        supporting.append(ev.statement)
                    elif any(w in ev_stmt for w in ("lower", "decreased", "drop", "fell", "declined")):
                        supporting.append(ev.statement)
                    elif any(w in ev_stmt for w in ("higher", "increased", "grew", "stable", "constant")):
                        contradicting.append(ev.statement)

            # Evaluate Segment / Dimensional Concentration Hypothesis
            elif "segment" in h_id or "concentrated" in stmt_lower:
                if ev.evidence_type in (EvidenceType.RANKING, EvidenceType.COMPARISON) or "top" in ev_stmt or "share" in ev_stmt or "contributed" in ev_stmt:
                    if ev.dimensions:
                        supporting.append(ev.statement)

            # Generic statement keyword matching fallback
            else:
                # Token overlap check
                stmt_tokens = set(re.findall(r"\w+", stmt_lower)) - {"is", "the", "and", "in", "of", "to", "primarily", "decline"}
                ev_tokens = set(re.findall(r"\w+", ev_stmt))
                if len(stmt_tokens & ev_tokens) >= 2:
                    if any(w in ev_stmt for w in ("lower", "decreased", "drop", "fell", "declined", "top")):
                        supporting.append(ev.statement)
                    elif any(w in ev_stmt for w in ("higher", "increased", "grew")):
                        contradicting.append(ev.statement)

        # Deduplicate evidence references
        supporting = list(dict.fromkeys(supporting))
        contradicting = list(dict.fromkeys(contradicting))

        # Determine evaluation status and confidence
        if supporting and not contradicting:
            new_status = HypothesisStatus.SUPPORTED
            confidence = 0.90
            rationale = f"Supported by verified evidence: {'; '.join(supporting[:2])}"
        elif contradicting and not supporting:
            new_status = HypothesisStatus.REJECTED
            confidence = 0.85
            rationale = f"Contradicted by verified evidence: {'; '.join(contradicting[:2])}"
        elif supporting and contradicting:
            new_status = HypothesisStatus.INCONCLUSIVE
            confidence = 0.50
            rationale = f"Mixed evidence: Supported by ({len(supporting)}) items, contradicted by ({len(contradicting)}) items."
        else:
            new_status = HypothesisStatus.INCONCLUSIVE
            confidence = 0.0
            rationale = "Insufficient evidence collected to prove or disprove hypothesis."

        return Hypothesis(
            hypothesis_id=hypothesis.hypothesis_id,
            statement=hypothesis.statement,
            status=new_status,
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            confidence=confidence,
            required_evidence=hypothesis.required_evidence,
            required_analysis_tasks=hypothesis.required_analysis_tasks,
            metrics=hypothesis.metrics,
            rationale=rationale,
        )

    @classmethod
    def calculate_segment_contributions(
        cls,
        rows: List[Dict[str, Any]],
        dimension_col: str,
        metric_col: str,
        time_col: Optional[str] = None,
    ) -> List[SegmentContribution]:
        """Perform pure deterministic Python calculation of baseline, current, delta, and share of decline."""
        if not rows:
            return []

        # 1. Multi-period comparison
        if time_col and any(time_col in r for r in rows):
            time_periods = sorted(list({str(r.get(time_col, "")) for r in rows if r.get(time_col)}))
            if len(time_periods) >= 2:
                prior_p, curr_p = time_periods[0], time_periods[-1]
                cat_prior: Dict[str, float] = {}
                cat_curr: Dict[str, float] = {}

                for r in rows:
                    cat = str(r.get(dimension_col, "Unknown"))
                    val = float(r.get(metric_col, 0.0) or 0.0)
                    p = str(r.get(time_col, ""))
                    if p == prior_p:
                        cat_prior[cat] = cat_prior.get(cat, 0.0) + val
                    elif p == curr_p:
                        cat_curr[cat] = cat_curr.get(cat, 0.0) + val

                all_cats = set(cat_prior.keys()).union(set(cat_curr.keys()))
                raw_items = []
                for cat in all_cats:
                    v0 = cat_prior.get(cat, 0.0)
                    v1 = cat_curr.get(cat, 0.0)
                    delta = v1 - v0
                    pct = ((delta / v0) * 100.0) if v0 != 0 else 0.0
                    raw_items.append((cat, v0, v1, delta, pct))
            else:
                raw_items = cls._compute_single_period_records(rows, dimension_col, metric_col)
        else:
            raw_items = cls._compute_single_period_records(rows, dimension_col, metric_col)

        # 2. Total negative delta calculation
        total_negative_delta = sum(item[3] for item in raw_items if item[3] < 0)

        contributions: List[SegmentContribution] = []
        for cat, v0, v1, delta, growth_pct in raw_items:
            if total_negative_delta < 0 and delta < 0:
                share_pct = round((delta / total_negative_delta) * 100.0, 2)
            else:
                share_pct = 0.0

            contributions.append(
                SegmentContribution(
                    dimension=dimension_col,
                    category=cat,
                    baseline_value=round(v0, 2),
                    current_value=round(v1, 2),
                    delta=round(delta, 2),
                    growth_pct=round(growth_pct, 2),
                    contribution_to_decline_pct=share_pct,
                    is_primary_driver=share_pct >= 30.0 or (share_pct > 0 and len(raw_items) == 1),
                )
            )

        # Rank negative contributors by largest absolute drop
        contributions.sort(key=lambda x: (x.delta < 0, abs(x.delta)), reverse=True)
        return contributions

    @classmethod
    def _compute_single_period_records(
        cls,
        rows: List[Dict[str, Any]],
        dimension_col: str,
        metric_col: str,
    ) -> List[Tuple[str, float, float, float, float]]:
        """Compute delta assuming pre-computed delta or current values in rows."""
        items = []
        for r in rows:
            cat = str(r.get(dimension_col, "Unknown"))
            val = float(r.get(metric_col, 0.0) or 0.0)
            prior = float(r.get("prior_value", r.get("previous_value", 0.0)) or 0.0)
            delta = val - prior if prior != 0 else (val if val < 0 else -val)
            pct = ((delta / prior) * 100.0) if prior != 0 else 0.0
            items.append((cat, prior, val, delta, pct))
        return items

    @classmethod
    def rank_hypotheses(cls, hypotheses: List[Hypothesis]) -> List[Hypothesis]:
        """Rank hypotheses deterministically: SUPPORTED > INCONCLUSIVE > PROPOSED > REJECTED."""
        def score_hypothesis(h: Hypothesis) -> Tuple[int, float, int]:
            if h.status == HypothesisStatus.SUPPORTED:
                status_tier = 4
            elif h.status == HypothesisStatus.INCONCLUSIVE and h.supporting_evidence:
                status_tier = 3
            elif h.status in (HypothesisStatus.PROPOSED, HypothesisStatus.TESTING):
                status_tier = 2
            elif h.status == HypothesisStatus.INCONCLUSIVE:
                status_tier = 1
            else:  # REJECTED
                status_tier = 0
            return (status_tier, h.confidence, len(h.supporting_evidence))

        return sorted(hypotheses, key=score_hypothesis, reverse=True)

    @classmethod
    def synthesize_root_cause_findings(
        cls,
        hypotheses: List[Hypothesis],
        contributions: Optional[List[SegmentContribution]] = None,
    ) -> List[str]:
        """Synthesize verified root cause findings grounded strictly in evaluated hypotheses and data."""
        findings: List[str] = []

        supported = [h for h in hypotheses if h.status == HypothesisStatus.SUPPORTED]
        rejected = [h for h in hypotheses if h.status == HypothesisStatus.REJECTED]
        inconclusive = [h for h in hypotheses if h.status == HypothesisStatus.INCONCLUSIVE]

        if supported:
            findings.append("الفرضيات المؤكدة بالأدلة (Supported Root Causes):")
            for h in supported:
                findings.append(f"✓ {h.statement} (درجة الثقة: {h.confidence * 100:.0f}%)")
                if h.rationale:
                    findings.append(f"   - الدليل: {h.rationale}")

        if contributions:
            primary_drivers = [c for c in contributions if c.is_primary_driver]
            if primary_drivers:
                findings.append("القطاعات والمحركات الأساسية الأكثر مساهمة في التراجع (Primary Drivers):")
                for c in primary_drivers:
                    findings.append(
                        f"• القطاع '{c.category}' (بُعد {c.dimension}): تراجع بمقدار {c.delta:+,.2f} "
                        f"({c.growth_pct:+.1f}%) وساهم بنسبة {c.contribution_to_decline_pct:.1f}% من إجمالي التراجع."
                    )

        if rejected:
            findings.append("الفرضيات المستبعدة والمرفوضة بالأدلة (Rejected Hypotheses):")
            for h in rejected:
                findings.append(f"✗ {h.statement}")
                if h.rationale:
                    findings.append(f"   - سبب الاستبعاد: {h.rationale}")

        if not supported and not rejected:
            findings.append("لم يتم التوصل إلى سبب جذري قاطع ومؤكد بالأدلة المتاحة (Inconclusive Investigation).")

        return findings
