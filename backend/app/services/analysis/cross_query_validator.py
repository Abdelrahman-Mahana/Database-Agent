"""Cross-Query Validator & Grounding Readiness Assessment Layer (Phase 7).

Responsible for:
1. Multi-query consistency, reconciliation, and contradiction checks (totals vs segments, metric conflicts, time/dimension mismatches).
2. Deterministic Completeness Score calculation (0–100 scale).
3. Deterministic Confidence Score calculation (0.0–1.0 scale) separate from completeness.
4. Grounding readiness breakdown (verified vs unverified vs issue-flagged facts) before final report generation.
"""
from dataclasses import dataclass, field
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.services.analysis.investigation_models import (
    EvidenceItem,
    EvidenceType,
    InvestigationPlan,
    InvestigationState,
    InvestigationStatus,
    QueryExecutionRecord,
    QueryExecutionStatus,
    QueryTask,
    QueryTaskStatus,
    ValidationIssue,
    ValidationIssueStatus,
    ValidationIssueType,
    ValidationSeverity,
)

logger = logging.getLogger(__name__)


# ─── Grounding Readiness Data Classes ───

@dataclass
class GroundingReadiness:
    """Categorizes accumulated evidence for grounded reporting readiness."""
    verified_facts: List[EvidenceItem] = field(default_factory=list)
    unverified_facts: List[EvidenceItem] = field(default_factory=list)
    issue_facts: List[Dict[str, Any]] = field(default_factory=list)
    is_ready_for_report: bool = True
    verification_rate: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verified_count": len(self.verified_facts),
            "unverified_count": len(self.unverified_facts),
            "issue_count": len(self.issue_facts),
            "is_ready_for_report": self.is_ready_for_report,
            "verification_rate": self.verification_rate,
            "verified_statements": [e.statement for e in self.verified_facts],
            "unverified_statements": [e.statement for e in self.unverified_facts],
        }


@dataclass
class ValidationReport:
    """Complete multi-query validation and consistency assessment report."""
    is_valid: bool
    issues: List[ValidationIssue]
    completeness_score: float  # 0.0 to 100.0 scale
    confidence_score: float    # 0.0 to 1.0 scale
    grounding_readiness: GroundingReadiness
    reconciliation_checked: bool
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "issues": [i.model_dump() for i in self.issues],
            "completeness_score": self.completeness_score,
            "confidence_score": self.confidence_score,
            "grounding_readiness": self.grounding_readiness.to_dict(),
            "reconciliation_checked": self.reconciliation_checked,
            "summary": self.summary,
        }


# ─── Cross Query Validator Engine ───

class CrossQueryValidator:
    """Validates cross-query consistency and computes completeness/confidence before final reporting."""

    @classmethod
    def validate(
        cls,
        state: InvestigationState,
        tolerance_pct: float = 0.05,
    ) -> ValidationReport:
        """Run all consistency checks on the accumulated query results and evidence."""
        issues: List[ValidationIssue] = []
        reconciliation_checked = False

        if not state.completed_queries:
            # Empty execution
            readiness = GroundingReadiness(
                verified_facts=[],
                unverified_facts=[],
                issue_facts=[],
                is_ready_for_report=False,
                verification_rate=0.0,
            )
            return ValidationReport(
                is_valid=True,
                issues=[],
                completeness_score=0.0,
                confidence_score=0.0,
                grounding_readiness=readiness,
                reconciliation_checked=False,
                summary="No executed queries to validate.",
            )

        # 1. Total Reconciliation Check (Aggregate vs Breakdown Sum)
        rec_issues, rec_ran = cls._check_total_reconciliation(state, tolerance_pct)
        issues.extend(rec_issues)
        if rec_ran:
            reconciliation_checked = True

        # 2. Metric Conflict Check
        metric_issues = cls._check_metric_conflicts(state)
        issues.extend(metric_issues)

        # 3. Time / Period Consistency Check
        time_issues = cls._check_time_consistency(state)
        issues.extend(time_issues)

        # 4. Dimension Consistency Check
        dim_issues = cls._check_dimension_consistency(state)
        issues.extend(dim_issues)

        # 5. Duplicate Evidence Check
        dup_issues = cls._check_duplicate_evidence(state)
        issues.extend(dup_issues)

        # 6. Evaluate Grounding Readiness
        grounding_readiness = cls._evaluate_grounding_readiness(state, issues)

        # 7. Compute Scores (Separated Completeness 0–100 vs Confidence 0.0–1.0)
        completeness_score = cls._compute_completeness_score(state, issues)
        confidence_score = cls._compute_confidence_score(state, issues, grounding_readiness)

        has_critical = any(i.severity == ValidationSeverity.CRITICAL for i in issues)
        is_valid = not has_critical

        # Build Summary
        if not issues:
            summary = f"All {len(state.completed_queries)} queries validated successfully with 0 consistency issues."
        else:
            issue_types = ", ".join(list({i.type.value for i in issues}))
            summary = f"Detected {len(issues)} consistency issue(s) ({issue_types}). Validation valid={is_valid}."

        return ValidationReport(
            is_valid=is_valid,
            issues=issues,
            completeness_score=completeness_score,
            confidence_score=confidence_score,
            grounding_readiness=grounding_readiness,
            reconciliation_checked=reconciliation_checked,
            summary=summary,
        )

    @classmethod
    def _check_total_reconciliation(
        cls,
        state: InvestigationState,
        tolerance_pct: float,
    ) -> Tuple[List[ValidationIssue], bool]:
        """Check if an aggregate overall total query matches the sum of sub-segment queries."""
        issues: List[ValidationIssue] = []
        ran = False

        # Map plan tasks by query_id if plan exists
        task_map = {t.query_id: t for t in state.plan.query_tasks} if state.plan else {}

        for i, q1 in enumerate(state.completed_queries):
            if q1.status != QueryExecutionStatus.SUCCESS or not q1.rows:
                continue
            # q1 is total if 1 row and mostly pure metric
            row1 = q1.rows[0]
            dim1 = [k for k, v in row1.items() if not isinstance(v, (int, float)) or isinstance(v, bool)]
            metric_cols1 = [k for k, v in row1.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
            task1 = task_map.get(q1.query_id)

            for j, q2 in enumerate(state.completed_queries):
                if i == j or q2.status != QueryExecutionStatus.SUCCESS or not q2.rows:
                    continue
                row2 = q2.rows[0]
                dim2 = [k for k, v in row2.items() if not isinstance(v, (int, float)) or isinstance(v, bool)]
                task2 = task_map.get(q2.query_id)

                # Check task metric compatibility if task metadata is available
                if task1 and task2 and task1.required_metrics and task2.required_metrics:
                    shared_metrics = set(m.lower() for m in task1.required_metrics) & set(m.lower() for m in task2.required_metrics)
                    if not shared_metrics:
                        continue

                # If q1 has fewer dimensions than q2 (or q1 is single row without dims and q2 has dims or multiple rows)
                if (not dim1 and dim2) or (len(q1.rows) == 1 and (len(q2.rows) > 1 or dim2)):
                    for metric_name in metric_cols1:
                        if all(metric_name in r for r in q2.rows):
                            agg_val = float(row1.get(metric_name, 0.0))
                            segment_sum = sum(
                                float(r.get(metric_name, 0.0) or 0.0)
                                for r in q2.rows
                                if isinstance(r.get(metric_name), (int, float))
                            )
                            ran = True
                            diff = abs(agg_val - segment_sum)
                            diff_pct = (diff / agg_val) if agg_val != 0 else 0.0

                            if diff_pct > tolerance_pct:
                                severity = ValidationSeverity.CRITICAL if diff_pct > 0.15 else ValidationSeverity.WARNING
                                issues.append(
                                    ValidationIssue(
                                        issue_id=f"iss_rec_{q1.query_id}_{q2.query_id}_{metric_name}",
                                        type=ValidationIssueType.RECONCILIATION,
                                        severity=severity,
                                        query_ids=[q1.query_id, q2.query_id],
                                        description=(
                                            f"Reconciliation discrepancy for metric '{metric_name}': "
                                            f"Total query '{q1.query_id}' reported {agg_val:,.2f}, but breakdown query '{q2.query_id}' "
                                            f"summed to {segment_sum:,.2f} (diff: {diff:,.2f} or {diff_pct * 100:.1f}%)."
                                        ),
                                        expected=agg_val,
                                        actual=segment_sum,
                                    )
                                )
        return issues, ran

    @classmethod
    def _check_metric_conflicts(cls, state: InvestigationState) -> List[ValidationIssue]:
        """Check for conflicting numeric values for identical metrics and dimensions."""
        issues: List[ValidationIssue] = []
        seen_metrics: Dict[Tuple[str, str], Tuple[str, float]] = {}

        for ev in state.evidence:
            if ev.metric and isinstance(ev.value, (int, float)) and not isinstance(ev.value, bool):
                dim_key = str(sorted(ev.dimensions.items())) if ev.dimensions else "global"
                key = (ev.metric.lower(), dim_key)
                current_val = float(ev.value)
                source = ev.source_query_id or "unknown"

                if key in seen_metrics:
                    prev_source, prev_val = seen_metrics[key]
                    if prev_source != source and abs(current_val - prev_val) > 1e-4:
                        issues.append(
                            ValidationIssue(
                                issue_id=f"iss_conflict_{prev_source}_{source}_{ev.metric}",
                                type=ValidationIssueType.METRIC_CONFLICT,
                                severity=ValidationSeverity.CRITICAL,
                                query_ids=[prev_source, source],
                                description=(
                                    f"Metric conflict for '{ev.metric}' (dimensions: {dim_key}): "
                                    f"Query '{prev_source}' produced {prev_val:,.2f} whereas query '{source}' produced {current_val:,.2f}."
                                ),
                                expected=prev_val,
                                actual=current_val,
                            )
                        )
                else:
                    seen_metrics[key] = (source, current_val)
        return issues

    @classmethod
    def _check_time_consistency(cls, state: InvestigationState) -> List[ValidationIssue]:
        """Check for conflicting temporal grains or period definitions."""
        issues: List[ValidationIssue] = []
        if not state.plan:
            return issues

        # Check if tasks with identical parent analysis task have conflicting grains
        task_grains: Dict[str, Tuple[str, str]] = {}
        for t in state.plan.query_tasks:
            if t.expected_grain and t.analytical_task_id:
                if t.analytical_task_id in task_grains:
                    prev_id, prev_grain = task_grains[t.analytical_task_id]
                    if prev_grain.lower() != t.expected_grain.lower():
                        issues.append(
                            ValidationIssue(
                                issue_id=f"iss_time_{prev_id}_{t.query_id}",
                                type=ValidationIssueType.TIME_MISMATCH,
                                severity=ValidationSeverity.WARNING,
                                query_ids=[prev_id, t.query_id],
                                description=(
                                    f"Time grain mismatch for analytical task '{t.analytical_task_id}': "
                                    f"Query '{prev_id}' expected '{prev_grain}', but query '{t.query_id}' expected '{t.expected_grain}'."
                                ),
                                expected=prev_grain,
                                actual=t.expected_grain,
                            )
                        )
                else:
                    task_grains[t.analytical_task_id] = (t.query_id, t.expected_grain)
        return issues

    @classmethod
    def _check_dimension_consistency(cls, state: InvestigationState) -> List[ValidationIssue]:
        """Check for dimension naming and domain inconsistencies."""
        issues: List[ValidationIssue] = []
        # Detect empty string or 'unknown' dominating dimension breakdown
        for rec in state.completed_queries:
            if rec.status == QueryExecutionStatus.SUCCESS and len(rec.rows) > 1:
                first_row = rec.rows[0]
                dim_cols = [k for k, v in first_row.items() if not isinstance(v, (int, float))]
                for d in dim_cols:
                    vals = [str(r.get(d, "")) for r in rec.rows]
                    unknown_count = sum(1 for v in vals if v.lower() in ("unknown", "null", "none", "", "n/a"))
                    if len(vals) > 0 and (unknown_count / len(vals)) > 0.5:
                        issues.append(
                            ValidationIssue(
                                issue_id=f"iss_dim_{rec.query_id}_{d}",
                                type=ValidationIssueType.DIMENSION_MISMATCH,
                                severity=ValidationSeverity.INFO,
                                query_ids=[rec.query_id],
                                description=f"Dimension '{d}' in query '{rec.query_id}' contains >50% unknown/missing category values.",
                                expected="Valid category names",
                                actual=f"{unknown_count}/{len(vals)} unknown",
                            )
                        )
        return issues

    @classmethod
    def _check_duplicate_evidence(cls, state: InvestigationState) -> List[ValidationIssue]:
        """Detect duplicate evidence statements produced across distinct queries."""
        issues: List[ValidationIssue] = []
        seen_stmts: Dict[str, str] = {}

        for ev in state.evidence:
            norm_stmt = ev.statement.strip().lower()
            src = ev.source_query_id or "unknown"
            if norm_stmt in seen_stmts:
                prev_src = seen_stmts[norm_stmt]
                if prev_src != src:
                    issues.append(
                        ValidationIssue(
                            issue_id=f"iss_dup_{prev_src}_{src}",
                            type=ValidationIssueType.DUPLICATE_EVIDENCE,
                            severity=ValidationSeverity.INFO,
                            query_ids=[prev_src, src],
                            description=f"Duplicate evidence statement produced by both '{prev_src}' and '{src}': '{ev.statement}'",
                        )
                    )
            else:
                seen_stmts[norm_stmt] = src
        return issues

    @classmethod
    def _evaluate_grounding_readiness(
        cls,
        state: InvestigationState,
        issues: List[ValidationIssue],
    ) -> GroundingReadiness:
        """Classify evidence items into verified, unverified, and issue-impacted categories."""
        critical_query_ids: Set[str] = set()
        for i in issues:
            if i.severity == ValidationSeverity.CRITICAL:
                critical_query_ids.update(i.query_ids)

        verified: List[EvidenceItem] = []
        unverified: List[EvidenceItem] = []
        issue_facts: List[Dict[str, Any]] = []

        for ev in state.evidence:
            has_crit_issue = bool(ev.source_query_id and ev.source_query_id in critical_query_ids)
            if ev.verified and not has_crit_issue and ev.confidence >= 0.7:
                verified.append(ev)
            elif has_crit_issue:
                unverified.append(ev)
                rel_issues = [i.description for i in issues if ev.source_query_id in i.query_ids]
                issue_facts.append({
                    "evidence_id": ev.evidence_id,
                    "statement": ev.statement,
                    "issues": rel_issues,
                })
            else:
                unverified.append(ev)

        total_ev = len(state.evidence)
        verification_rate = round(len(verified) / total_ev, 2) if total_ev > 0 else 0.0
        is_ready = len(critical_query_ids) == 0 and len(verified) > 0

        return GroundingReadiness(
            verified_facts=verified,
            unverified_facts=unverified,
            issue_facts=issue_facts,
            is_ready_for_report=is_ready,
            verification_rate=verification_rate,
        )

    @classmethod
    def _compute_completeness_score(
        cls,
        state: InvestigationState,
        issues: List[ValidationIssue],
    ) -> float:
        """Compute deterministic Completeness Score on a 0.0 to 100.0 scale."""
        if not state.plan or not state.plan.query_tasks:
            return 100.0 if state.completed_queries else 0.0

        total_tasks = len(state.plan.query_tasks)
        completed_count = len([t for t in state.plan.query_tasks if t.status == QueryTaskStatus.COMPLETED])
        failed_count = len([t for t in state.plan.query_tasks if t.status == QueryTaskStatus.FAILED])

        task_coverage = completed_count / total_tasks
        evidence_coverage = state.completeness_score  # from Phase 4

        # Validation status factor
        critical_count = sum(1 for i in issues if i.severity == ValidationSeverity.CRITICAL)
        warning_count = sum(1 for i in issues if i.severity == ValidationSeverity.WARNING)
        val_factor = max(0.0, 1.0 - (0.25 * critical_count) - (0.10 * warning_count))

        # Failed tasks penalty
        failed_penalty = (failed_count / total_tasks) * 0.30

        raw_score = (
            (0.40 * task_coverage)
            + (0.40 * evidence_coverage)
            + (0.20 * val_factor)
            - failed_penalty
        )
        final_score = max(0.0, min(100.0, round(raw_score * 100.0, 1)))
        return final_score

    @classmethod
    def _compute_confidence_score(
        cls,
        state: InvestigationState,
        issues: List[ValidationIssue],
        grounding: GroundingReadiness,
    ) -> float:
        """Compute deterministic Confidence Score on a 0.0 to 1.0 scale (distinct from completeness)."""
        if not state.evidence:
            return 0.0

        # Base confidence from verified evidence rate
        base_confidence = grounding.verification_rate

        # Deductions
        critical_deduction = sum(0.25 for i in issues if i.severity == ValidationSeverity.CRITICAL)
        warning_deduction = sum(0.08 for i in issues if i.severity == ValidationSeverity.WARNING)
        failed_deduction = 0.15 if any(q.status == QueryExecutionStatus.FAILED for q in state.completed_queries) else 0.0

        score = base_confidence - critical_deduction - warning_deduction - failed_deduction
        return max(0.0, min(1.0, round(score, 2)))
