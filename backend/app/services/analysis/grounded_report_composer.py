"""Grounded Analysis Context & Report Composer (Phase 8).

Ensures the final answer is strictly structured and grounded in verified evidence,
with numerical traceability, query provenance citations, adaptive structure for simple vs complex questions,
and explicit uncertainty handling without LLM hallucination.
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
    QueryExecutionRecord,
    QueryExecutionStatus,
    ValidationIssue,
    ValidationIssueType,
    ValidationSeverity,
)
from app.services.analysis.cross_query_validator import (
    CrossQueryValidator,
    GroundingReadiness,
    ValidationReport,
)
from app.services.analysis.models import AnalysisResult

logger = logging.getLogger(__name__)


# ─── 1. Grounded Analysis Context ───

@dataclass
class GroundedAnalysisContext:
    """Structured, verified analytical context prepared before final report composition."""
    original_question: str
    analytical_goal: str
    completed_analysis_tasks: List[str] = field(default_factory=list)
    verified_evidence: List[EvidenceItem] = field(default_factory=list)
    unverified_evidence: List[EvidenceItem] = field(default_factory=list)
    validation_issues: List[ValidationIssue] = field(default_factory=list)
    hypotheses: List[Hypothesis] = field(default_factory=list)
    supported_root_causes: List[str] = field(default_factory=list)
    key_metrics: Dict[str, Any] = field(default_factory=dict)
    trends: List[Dict[str, Any]] = field(default_factory=list)
    confidence_score: float = 1.0  # 0.0 to 1.0
    completeness_score: float = 100.0  # 0.0 to 100.0
    source_query_ids: List[str] = field(default_factory=list)
    is_complete: bool = True
    is_simple_lookup: bool = False

    @classmethod
    def from_investigation(
        cls,
        state: InvestigationState,
        analysis_result: Optional[AnalysisResult] = None,
        validation_report: Optional[ValidationReport] = None,
        question: Optional[str] = None,
    ) -> "GroundedAnalysisContext":
        """Construct GroundedAnalysisContext from investigation runtime state."""
        q = question or (state.plan.question if state.plan else "Data Investigation")
        goal = state.plan.goal if (state.plan and state.plan.goal) else q

        # Run validation if report not pre-computed
        val_rep = validation_report or CrossQueryValidator.validate(state)

        # Extract verified vs unverified
        verified = val_rep.grounding_readiness.verified_facts
        unverified = val_rep.grounding_readiness.unverified_facts

        # Completed tasks
        completed_tasks: List[str] = []
        if state.plan:
            for t in state.plan.query_tasks:
                if t.status.value == "completed":
                    desc = f"{t.query_id}: {t.sub_question or t.purpose}"
                    completed_tasks.append(desc)

        # Supported root causes from active hypotheses
        supported_causes: List[str] = []
        for h in state.active_hypotheses:
            if h.status == HypothesisStatus.SUPPORTED:
                supported_causes.append(h.statement)

        # Key metrics extraction
        metrics: Dict[str, Any] = {}
        for ev in verified:
            if ev.metric and ev.value is not None:
                metrics[ev.metric] = ev.value
        if analysis_result and analysis_result.metrics:
            metrics.update(analysis_result.metrics)

        # Query IDs
        q_ids = [q.query_id for q in state.completed_queries if q.status == QueryExecutionStatus.SUCCESS]

        # Is simple lookup?
        is_simple = len(state.completed_queries) <= 1 and len(state.evidence) <= 2 and not state.active_hypotheses

        is_complete = val_rep.completeness_score >= 75.0 and not any(
            i.severity == ValidationSeverity.CRITICAL for i in val_rep.issues
        )

        return cls(
            original_question=q,
            analytical_goal=goal,
            completed_analysis_tasks=completed_tasks,
            verified_evidence=verified,
            unverified_evidence=unverified,
            validation_issues=val_rep.issues,
            hypotheses=state.active_hypotheses,
            supported_root_causes=supported_causes,
            key_metrics=metrics,
            trends=[],
            confidence_score=val_rep.confidence_score,
            completeness_score=val_rep.completeness_score,
            source_query_ids=q_ids,
            is_complete=is_complete,
            is_simple_lookup=is_simple,
        )


# ─── 2. Grounded Report Composer ───

class GroundedReportComposer:
    """Composes high-quality, verified analyst reports grounded entirely in evidence and provenance."""

    @classmethod
    def compose(
        cls,
        context: GroundedAnalysisContext,
        is_arabic: Optional[bool] = None,
    ) -> str:
        """Compose final report adapting structure based on question complexity and evidence state."""
        if is_arabic is None:
            is_arabic = any("\u0600" <= c <= "\u06FF" for c in context.original_question)

        # Simple lookup / Single metric query
        if context.is_simple_lookup:
            return cls._compose_simple_report(context, is_arabic=is_arabic)

        # Complex / Multi-query investigative question
        return cls._compose_complex_report(context, is_arabic=is_arabic)

    @classmethod
    def _compose_simple_report(
        cls,
        context: GroundedAnalysisContext,
        is_arabic: bool,
    ) -> str:
        """Compose clean, direct response for simple lookups or single-metric queries."""
        if not context.verified_evidence:
            if is_arabic:
                return (
                    f"الخلاصة: لم يتم العثور على بيانات مؤكدة مطابقة لسؤالك: **{context.original_question}**.\n\n"
                    f"💡 يرجى التأكد من دقة معايير البحث أو اختيار نطاق زمني أوسع."
                )
            return (
                f"Summary: No verified data found matching: **{context.original_question}**.\n\n"
                f"💡 Please refine your query parameters or broaden the time range."
            )

        ev = context.verified_evidence[0]
        src_tag = f" (المصدر: {ev.source_query_id})" if (ev.source_query_id and is_arabic) else (f" (Source: {ev.source_query_id})" if ev.source_query_id else "")

        if is_arabic:
            lines = [
                f"الخلاصة: {ev.statement}{src_tag}.\n",
                f"💡 **تفاصيل إضافية**:",
                f"- **درجة الموثوقية**: البيانات مؤكدة مباشرة من واقع قاعدة البيانات بنسبة ثقة {int(context.confidence_score * 100)}%.",
            ]
            if len(context.verified_evidence) > 1:
                lines.append("- **حقائق مساندة**:")
                for extra in context.verified_evidence[1:4]:
                    extra_tag = f" ({extra.source_query_id})" if extra.source_query_id else ""
                    lines.append(f"  * {extra.statement}{extra_tag}")
            return "\n".join(lines)

        lines = [
            f"Direct Answer: {ev.statement}{src_tag}.\n",
            f"💡 **Context & Accuracy**:",
            f"- **Precision**: Verified directly against database records with {int(context.confidence_score * 100)}% confidence.",
        ]
        if len(context.verified_evidence) > 1:
            lines.append("- **Supporting Facts**:")
            for extra in context.verified_evidence[1:4]:
                extra_tag = f" ({extra.source_query_id})" if extra.source_query_id else ""
                lines.append(f"  * {extra.statement}{extra_tag}")
        return "\n".join(lines)

    @classmethod
    def _compose_complex_report(
        cls,
        context: GroundedAnalysisContext,
        is_arabic: bool,
    ) -> str:
        """Compose structured executive report with provenance citations and caveat handling."""
        sections: List[str] = []

        # ── 1. Executive Answer ──
        if is_arabic:
            sections.append("### 📌 الإجابة التنفيذية (Executive Answer)")
            exec_ans = cls._build_executive_summary(context, is_arabic=True)
            sections.append(exec_ans)
        else:
            sections.append("### 📌 Executive Answer")
            exec_ans = cls._build_executive_summary(context, is_arabic=False)
            sections.append(exec_ans)

        sections.append("")

        # ── 2. Key Findings (with query provenance) ──
        if is_arabic:
            sections.append("### 🔍 النتائج الرئيسية (Key Findings)")
            findings_lines = cls._build_provenance_findings(context, is_arabic=True)
            sections.extend(findings_lines)
        else:
            sections.append("### 🔍 Key Findings")
            findings_lines = cls._build_provenance_findings(context, is_arabic=False)
            sections.extend(findings_lines)

        sections.append("")

        # ── 3. What Changed (Changes & Variances) ──
        comparison_evidence = [e for e in context.verified_evidence if e.evidence_type in (EvidenceType.COMPARISON, EvidenceType.TREND)]
        if comparison_evidence:
            if is_arabic:
                sections.append("### 📊 ما الذي تغير؟ (What Changed)")
                for ev in comparison_evidence:
                    src = f" [المصدر: {ev.source_query_id}]" if ev.source_query_id else ""
                    sections.append(f"- {ev.statement}{src}")
            else:
                sections.append("### 📊 What Changed")
                for ev in comparison_evidence:
                    src = f" [Source: {ev.source_query_id}]" if ev.source_query_id else ""
                    sections.append(f"- {ev.statement}{src}")
            sections.append("")

        # ── 4. Why It Changed (Root Causes & Hypotheses) ──
        if context.hypotheses or context.supported_root_causes:
            if is_arabic:
                sections.append("### 💡 أسباب ودوافع التغيير (Root Cause Analysis)")
                for h in context.hypotheses:
                    status_ar = {
                        HypothesisStatus.SUPPORTED: "مؤكد بأدلة قاطعة ✅",
                        HypothesisStatus.REJECTED: "مستبعد / غير صحيح ❌",
                        HypothesisStatus.INCONCLUSIVE: "غير حاسم ⚠️",
                        HypothesisStatus.PROPOSED: "قيد الدراسة ⏳",
                        HypothesisStatus.TESTING: "قيد الاختبار 🔍",
                    }.get(h.status, h.status.value)
                    sections.append(f"- **{h.statement}**: {status_ar}")
                    if h.supporting_evidence:
                        for s in h.supporting_evidence:
                            sections.append(f"  * دليل مؤيد: {s}")
                    if h.contradicting_evidence:
                        for c in h.contradicting_evidence:
                            sections.append(f"  * دليل نافٍ: {c}")
            else:
                sections.append("### 💡 Why It Changed (Root Cause Analysis)")
                for h in context.hypotheses:
                    status_en = {
                        HypothesisStatus.SUPPORTED: "Supported by evidence ✅",
                        HypothesisStatus.REJECTED: "Rejected / Disproven ❌",
                        HypothesisStatus.INCONCLUSIVE: "Inconclusive ⚠️",
                        HypothesisStatus.PROPOSED: "Proposed ⏳",
                        HypothesisStatus.TESTING: "Testing 🔍",
                    }.get(h.status, h.status.value)
                    sections.append(f"- **{h.statement}**: {status_en}")
                    if h.supporting_evidence:
                        for s in h.supporting_evidence:
                            sections.append(f"  * Supporting evidence: {s}")
                    if h.contradicting_evidence:
                        for c in h.contradicting_evidence:
                            sections.append(f"  * Contradicting evidence: {c}")
            sections.append("")

        # ── 5. Supporting Evidence (Table or list of all verified points) ──
        if context.verified_evidence:
            if is_arabic:
                sections.append("### 📑 الأدلة والحقائق الموثقة (Supporting Evidence)")
                for ev in context.verified_evidence:
                    src = f" (`{ev.source_query_id}`)" if ev.source_query_id else ""
                    sections.append(f"- **{ev.evidence_id}**{src}: {ev.statement}")
            else:
                sections.append("### 📑 Supporting Evidence")
                for ev in context.verified_evidence:
                    src = f" (`{ev.source_query_id}`)" if ev.source_query_id else ""
                    sections.append(f"- **{ev.evidence_id}**{src}: {ev.statement}")
            sections.append("")

        # ── 6. Caveats & Limitations ──
        caveats = cls._build_caveats(context, is_arabic)
        if caveats:
            if is_arabic:
                sections.append("### ⚠️ القيود والملاحظات (Caveats & Limitations)")
            else:
                sections.append("### ⚠️ Caveats & Limitations")
            sections.extend(caveats)
            sections.append("")

        # ── 7. Confidence & Completeness ──
        comp_pct = int(context.completeness_score)
        conf_pct = int(context.confidence_score * 100)
        sources_str = ", ".join(context.source_query_ids) if context.source_query_ids else "N/A"

        if is_arabic:
            sections.append("### 🎯 درجة الثقة والاكتمال (Confidence & Completeness)")
            sections.append(f"- **اكتمال التحقيق**: `{comp_pct}%`")
            sections.append(f"- **درجة الموثوقية**: `{conf_pct}%`")
            sections.append(f"- **الاستعلامات المنفذة**: `{sources_str}`")
        else:
            sections.append("### 🎯 Confidence & Provenance")
            sections.append(f"- **Investigation Completeness**: `{comp_pct}%`")
            sections.append(f"- **Evidence Confidence**: `{conf_pct}%`")
            sections.append(f"- **Source Queries**: `{sources_str}`")

        return "\n".join(sections)

    @classmethod
    def _build_executive_summary(cls, context: GroundedAnalysisContext, is_arabic: bool) -> str:
        """Generate grounded executive summary reflecting certainty or incompleteness."""
        if not context.is_complete:
            unv_count = len(context.unverified_evidence)
            issues_count = len([i for i in context.validation_issues if i.severity in (ValidationSeverity.CRITICAL, ValidationSeverity.WARNING)])
            if is_arabic:
                return (
                    f"تشير الأدلة المؤكدة إلى نتائج أولية حول **{context.original_question}**، "
                    f"ولكن التحقيق غير مكتمل بنسبة 100% (الاكتمال: {int(context.completeness_score)}%) مع وجود "
                    f"{issues_count} ملاحظة/تباين بحاجة لمزيد من التحقق."
                )
            return (
                f"Verified evidence provides preliminary insights into **{context.original_question}**, "
                f"however the investigation is partially complete ({int(context.completeness_score)}% completeness) "
                f"with {issues_count} unresolved data variance/validation warning(s)."
            )

        # Fully grounded
        if context.supported_root_causes:
            cause_summary = "، و".join(context.supported_root_causes) if is_arabic else ", and ".join(context.supported_root_causes)
            if is_arabic:
                return f"بناءً على التحليل المدعوم بالأدلة، فإن المحرك الأساسي هو: **{cause_summary}**."
            return f"Based on verified cross-query analysis, the primary driver is: **{cause_summary}**."

        if context.verified_evidence:
            lead = context.verified_evidence[0].statement
            if is_arabic:
                return f"استناداً إلى البيانات المسترجعة، يتبين أن: **{lead}**."
            return f"Based on retrieved database records: **{lead}**."

        return "تم الانتهاء من التحقيق واستخراج المؤشرات المتاحة." if is_arabic else "Investigation completed with available indicators."

    @classmethod
    def _build_provenance_findings(cls, context: GroundedAnalysisContext, is_arabic: bool) -> List[str]:
        """Format findings with explicit source query citations."""
        lines: List[str] = []
        for ev in context.verified_evidence[:6]:
            src = f" (المصادر: {ev.source_query_id})" if (ev.source_query_id and is_arabic) else (f" (Sources: {ev.source_query_id})" if ev.source_query_id else "")
            lines.append(f"- {ev.statement}{src}")

        for unv in context.unverified_evidence[:3]:
            unv_tag = " [غير مؤكد]" if is_arabic else " [unverified]"
            lines.append(f"- {unv.statement}{unv_tag}")

        if not lines:
            lines.append("- لا توجد نتائج إضافية." if is_arabic else "- No additional findings.")
        return lines

    @classmethod
    def _build_caveats(cls, context: GroundedAnalysisContext, is_arabic: bool) -> List[str]:
        """Generate transparent caveats from validation issues and unverified data."""
        lines: List[str] = []
        for iss in context.validation_issues:
            if iss.severity in (ValidationSeverity.CRITICAL, ValidationSeverity.WARNING):
                if is_arabic:
                    lines.append(f"- **تنبيه اتساق [{iss.type.value}]**: {iss.description}")
                else:
                    lines.append(f"- **Validation Warning [{iss.type.value}]**: {iss.description}")

        if context.unverified_evidence:
            count = len(context.unverified_evidence)
            if is_arabic:
                lines.append(f"- تم استبعاد أو وسم {count} نقطة بيانات لعدم اكتمال التحقق المباشر من اتساقها.")
            else:
                lines.append(f"- {count} data point(s) were flagged as unverified due to reconciliation/conflict checks.")

        return lines
