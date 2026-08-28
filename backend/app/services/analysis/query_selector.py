"""Adaptive Query Selection Layer (Phase 5).

Responsible for:
1. Filtering eligible candidate QueryTasks (pending, dependencies satisfied, not executed, not blocked).
2. Evidence-aware deterministic scoring based on priority, unresolved goals, coverage, readiness, redundancy, and cost.
3. Budget-urgency awareness when remaining budget is constrained.
4. Deterministic tie-breaking without dynamic query creation.
5. Selection explanation generation for transparent decision provenance.
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
)

logger = logging.getLogger(__name__)


# ─── Configuration & Result Data Classes ───

@dataclass
class QuerySelectorConfig:
    """Configurable weights and tuning parameters for evidence-aware query selection."""
    priority_weight: float = 3.0
    unresolved_evidence_weight: float = 4.0
    analytical_coverage_weight: float = 2.5
    dependency_readiness_weight: float = 2.0
    redundancy_penalty_weight: float = 5.0
    cost_penalty_weight: float = 1.0
    budget_urgency_weight: float = 2.5


@dataclass
class CandidateEvaluation:
    """Detailed score breakdown and rationale for an eligible candidate QueryTask."""
    query_id: str
    task: QueryTask
    total_score: float
    priority_score: float
    unresolved_score: float
    analytical_score: float
    readiness_score: float
    redundancy_penalty: float
    cost_penalty: float
    budget_urgency_bonus: float
    reason: str
    is_redundant: bool = False


@dataclass
class QuerySelectionResult:
    """Outcome of the adaptive query selection process."""
    selected_task: Optional[QueryTask]
    selected_query_id: Optional[str]
    score: float
    reason: str
    eligible_candidates: List[CandidateEvaluation] = field(default_factory=list)


# ─── Query Selector Engine ───

class QuerySelector:
    """Selects the optimal next QueryTask from the investigation plan based on accumulated evidence."""

    def __init__(self, config: Optional[QuerySelectorConfig] = None):
        self.config = config or QuerySelectorConfig()

    def select_next_query(self, state: InvestigationState) -> QuerySelectionResult:
        """Evaluate all eligible QueryTasks in the active plan and select the best candidate."""
        if not state.plan or not state.plan.query_tasks:
            return QuerySelectionResult(
                selected_task=None,
                selected_query_id=None,
                score=0.0,
                reason="Investigation plan is empty or undefined.",
                eligible_candidates=[],
            )

        # 1. Budget exhaustion check
        if state.queries_executed >= state.max_queries:
            return QuerySelectionResult(
                selected_task=None,
                selected_query_id=None,
                score=0.0,
                reason=f"Query budget exhausted ({state.queries_executed}/{state.max_queries} executed).",
                eligible_candidates=[],
            )

        # 2. Dependency tracking and failure cascade
        completed_query_ids: Set[str] = {
            rec.query_id
            for rec in state.completed_queries
            if rec.status in (QueryExecutionStatus.SUCCESS, QueryExecutionStatus.EMPTY, QueryExecutionStatus.CACHED)
        }
        for t in state.plan.query_tasks:
            if t.status == QueryTaskStatus.COMPLETED:
                completed_query_ids.add(t.query_id)

        failed_or_blocked_ids: Set[str] = {
            t.query_id
            for t in state.plan.query_tasks
            if t.status in (QueryTaskStatus.FAILED, QueryTaskStatus.BLOCKED, QueryTaskStatus.SKIPPED)
        }
        for rec in state.completed_queries:
            if rec.status == QueryExecutionStatus.FAILED:
                failed_or_blocked_ids.add(rec.query_id)

        # Cascade blocked status to pending tasks with failed dependencies
        for task in state.plan.query_tasks:
            if task.status == QueryTaskStatus.PENDING:
                if any(dep in failed_or_blocked_ids for dep in task.depends_on):
                    task.status = QueryTaskStatus.BLOCKED
                    logger.info("QueryTask '%s' marked BLOCKED due to failed dependency", task.query_id)

        # 3. Filter candidates whose dependencies are fully satisfied and not already terminal
        candidate_tasks: List[Tuple[int, QueryTask]] = []
        for idx, task in enumerate(state.plan.query_tasks):
            if task.status == QueryTaskStatus.PENDING:
                # Check if all depends_on are completed
                deps_satisfied = all(dep in completed_query_ids for dep in task.depends_on)
                # Check if any depend on failed tasks
                dep_failed = any(dep in failed_or_blocked_ids for dep in task.depends_on)
                if deps_satisfied and not dep_failed:
                    candidate_tasks.append((idx, task))

        if not candidate_tasks:
            return QuerySelectionResult(
                selected_task=None,
                selected_query_id=None,
                score=0.0,
                reason="No eligible pending QueryTasks with satisfied dependencies remaining.",
                eligible_candidates=[],
            )

        # Early stopping optimization: if all questions resolved, 100% completeness and high confidence
        if state.completeness_score >= 1.0 and state.confidence_score >= 0.85 and len(state.unresolved_questions) == 0:
            return QuerySelectionResult(
                selected_task=None,
                selected_query_id=None,
                score=0.0,
                reason="Sufficient evidence collected with 100% completeness; early stopping optimization triggered.",
                eligible_candidates=[],
            )

        # 4. Evaluate and score each candidate
        evaluations: List[CandidateEvaluation] = []
        for idx, task in candidate_tasks:
            eval_item = self._evaluate_candidate(state, task, idx)
            evaluations.append(eval_item)

        # 5. Deterministic sorting: highest total_score, lowest priority int (highest priority), lowest plan index
        evaluations.sort(key=lambda c: (-c.total_score, c.task.priority, candidate_tasks[[t[1].query_id for t in candidate_tasks].index(c.query_id)][0]))

        top_candidate = evaluations[0]
        return QuerySelectionResult(
            selected_task=top_candidate.task,
            selected_query_id=top_candidate.query_id,
            score=top_candidate.total_score,
            reason=top_candidate.reason,
            eligible_candidates=evaluations,
        )

    def _evaluate_candidate(self, state: InvestigationState, task: QueryTask, plan_idx: int) -> CandidateEvaluation:
        """Compute the multi-factor evidence-aware score for a candidate QueryTask."""
        cfg = self.config

        # ── 1. Priority Score ──
        # priority 1 is highest; normalized so priority 1 -> 5.0, priority 2 -> 4.0, etc.
        norm_priority = max(1.0, 6.0 - float(task.priority))
        priority_score = norm_priority * cfg.priority_weight
        reasons_list: List[str] = [f"priority={task.priority}"]

        # ── 2. Unresolved Evidence Score ──
        unresolved_ratio = 0.0

        unresolved_qs = state.unresolved_questions or []
        task_text = f"{task.sub_question} {task.purpose} {task.expected_evidence or ''}".lower()

        if unresolved_qs:
            # Check if this task directly resolves any unresolved sub-questions
            matches = 0
            for uq in unresolved_qs:
                uq_lower = uq.lower()
                # Direct match or significant keyword match
                if uq_lower in task_text or task.sub_question.lower() in uq_lower:
                    matches += 1
                else:
                    # Token overlap check
                    uq_tokens = set(re.findall(r"\w+", uq_lower)) - {"what", "is", "the", "for", "and", "in", "how", "of", "to"}
                    task_tokens = set(re.findall(r"\w+", task_text))
                    if uq_tokens and len(uq_tokens & task_tokens) >= max(1, len(uq_tokens) // 2):
                        matches += 0.75
            unresolved_ratio = min(1.5, matches)
            if unresolved_ratio > 0:
                reasons_list.append("addresses unresolved investigation question")

        unresolved_score = unresolved_ratio * cfg.unresolved_evidence_weight

        # ── 3. Analytical Coverage Score ──
        # Check if the task retrieves new metrics or dimensions not yet covered in state.evidence
        existing_metrics: Set[str] = {e.metric.lower() for e in state.evidence if e.metric}
        existing_dims: Set[str] = set()
        for e in state.evidence:
            if e.dimensions:
                existing_dims.update(k.lower() for k in e.dimensions.keys())
                existing_dims.update(str(v).lower() for v in e.dimensions.values() if isinstance(v, (str, int)))

        task_metrics = [m.lower() for m in task.required_metrics]
        task_dims = [d.lower() for d in task.required_dimensions]

        new_metrics_count = sum(1 for m in task_metrics if m not in existing_metrics)
        new_dims_count = sum(1 for d in task_dims if d not in existing_dims)

        coverage_factor = 0.0
        if task_metrics or task_dims:
            total_targets = max(1, len(task_metrics) + len(task_dims))
            coverage_factor = (new_metrics_count + new_dims_count) / total_targets
        else:
            coverage_factor = 0.5  # Neutral bonus if no explicit targets

        analytical_score = coverage_factor * cfg.analytical_coverage_weight
        if coverage_factor >= 0.5 and (new_metrics_count > 0 or new_dims_count > 0):
            reasons_list.append("provides fresh metric/dimensional coverage")

        # ── 4. Dependency Readiness Score ──
        readiness_score = 0.0
        if task.depends_on:
            # All dependencies were satisfied
            readiness_score = 1.0 * cfg.dependency_readiness_weight
            reasons_list.append(f"dependencies satisfied ({', '.join(task.depends_on)})")
        else:
            readiness_score = 0.5 * cfg.dependency_readiness_weight

        # ── 5. Redundancy Penalty Check ──
        redundancy_penalty = 0.0
        is_redundant = False

        # If expected evidence is already fully collected
        if task.expected_evidence:
            exp_lower = task.expected_evidence.lower()
            if any(exp_lower in fact.lower() or fact.lower() in exp_lower for fact in state.known_facts):
                if task.can_be_skipped_if_answered:
                    redundancy_penalty = 1.5 * cfg.redundancy_penalty_weight
                    is_redundant = True
                    reasons_list.append("penalized: expected evidence already present in known facts")
                else:
                    redundancy_penalty = 0.5 * cfg.redundancy_penalty_weight

        # If metrics and dimensions are identical to an already completed query
        for completed_rec in state.completed_queries:
            if completed_rec.status in (QueryExecutionStatus.SUCCESS, QueryExecutionStatus.CACHED):
                if completed_rec.sub_question.strip().lower() == task.sub_question.strip().lower():
                    redundancy_penalty = 2.0 * cfg.redundancy_penalty_weight
                    is_redundant = True
                    reasons_list.append("penalized: identical query already executed")
                    break

        # ── 6. Cost / Complexity Penalty ──
        cost_val = getattr(task, "estimated_cost", 1.0)
        cost_penalty = max(0.0, (cost_val - 1.0)) * cfg.cost_penalty_weight
        if cost_penalty > 0:
            reasons_list.append(f"cost penalty: estimated cost {cost_val:.1f}")

        # ── 7. Budget Urgency Bonus ──
        remaining_budget = max(0, state.max_queries - state.queries_executed)
        budget_urgency_bonus = 0.0
        if remaining_budget == 1:
            # Low budget: prioritize high-priority, non-redundant essential tasks
            budget_urgency_bonus = (norm_priority / 5.0) * cfg.budget_urgency_weight
            reasons_list.append("boosted for final remaining query in budget")

        # ── Total Score ──
        total_score = round(
            priority_score
            + unresolved_score
            + analytical_score
            + readiness_score
            + budget_urgency_bonus
            - redundancy_penalty
            - cost_penalty,
            2,
        )

        main_reason = (
            f"'{task.query_id}' scored {total_score:.2f}: " + "; ".join(reasons_list)
            if reasons_list
            else f"'{task.query_id}' scored {total_score:.2f} based on priority {task.priority}"
        )

        return CandidateEvaluation(
            query_id=task.query_id,
            task=task,
            total_score=total_score,
            priority_score=round(priority_score, 2),
            unresolved_score=round(unresolved_score, 2),
            analytical_score=round(analytical_score, 2),
            readiness_score=round(readiness_score, 2),
            redundancy_penalty=round(redundancy_penalty, 2),
            cost_penalty=round(cost_penalty, 2),
            budget_urgency_bonus=round(budget_urgency_bonus, 2),
            reason=main_reason,
            is_redundant=is_redundant,
        )
