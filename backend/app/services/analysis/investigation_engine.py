"""Investigation Engine: manages adaptive multi-query scheduling, execution recording, state transitions, and stopping policies."""
from typing import Any, Dict, List, Optional, Set, Tuple
import logging

from app.services.analysis.investigation_models import (
    EvidenceItem,
    EvidenceType,
    Hypothesis,
    HypothesisStatus,
    InvestigationPlan,
    InvestigationState,
    InvestigationStatus,
    QueryExecutionRecord,
    QueryExecutionStatus,
    QueryTask,
    QueryTaskStatus,
)

logger = logging.getLogger(__name__)


class InvestigationEngine:
    """Manages deterministic scheduling and lifecycle of multi-query investigation workflows."""

    @staticmethod
    def initialize_investigation(
        plan: InvestigationPlan,
        max_queries: Optional[int] = None,
        max_reasoning_steps: Optional[int] = None,
    ) -> InvestigationState:
        """Initialize a new InvestigationState from an InvestigationPlan."""
        budget_queries = max_queries if max_queries is not None else plan.max_queries
        budget_reasoning = max_reasoning_steps if max_reasoning_steps is not None else plan.max_reasoning_steps

        # If plan has no tasks, mark immediately as completed
        init_status = InvestigationStatus.COMPLETED if not plan.query_tasks else InvestigationStatus.RUNNING

        return InvestigationState(
            plan=plan,
            current_query_task=None,
            completed_queries=[],
            query_results={},
            evidence=[],
            known_facts=[],
            unresolved_questions=[q.sub_question for q in plan.query_tasks if q.sub_question],
            hypotheses=list(plan.hypotheses),
            tested_hypotheses={},
            findings=[],
            completeness_score=1.0 if not plan.query_tasks else 0.0,
            confidence_score=0.0,
            queries_executed=0,
            max_queries=budget_queries,
            reasoning_steps=0,
            max_reasoning_steps=budget_reasoning,
            status=init_status,
        )

    @staticmethod
    def select_next_task(state: InvestigationState) -> Optional[QueryTask]:
        """Evidence-aware adaptive selection of the next eligible QueryTask (Phase 5)."""
        from app.services.analysis.query_selector import QuerySelector
        selector = QuerySelector()
        result = selector.select_next_query(state)
        return result.selected_task

    @staticmethod
    def select_next_task_with_explanation(state: InvestigationState) -> Any:
        """Select next QueryTask and return the full QuerySelectionResult explanation."""
        from app.services.analysis.query_selector import QuerySelector
        selector = QuerySelector()
        return selector.select_next_query(state)

    @staticmethod
    def record_execution_result(
        state: InvestigationState,
        task: QueryTask,
        sql: str,
        rows: Optional[List[Dict[str, Any]]] = None,
        exec_error: Optional[str] = None,
        execution_time_ms: float = 0.0,
        cache_hit: bool = False,
    ) -> QueryExecutionRecord:
        """Record the outcome of executing a QueryTask, update state and dependencies."""
        is_failure = bool(exec_error)
        is_empty = not is_failure and (rows is not None and len(rows) == 0)

        if is_failure:
            exec_status = QueryExecutionStatus.FAILED
            task.status = QueryTaskStatus.FAILED
        elif cache_hit:
            exec_status = QueryExecutionStatus.CACHED
            task.status = QueryTaskStatus.COMPLETED
        elif is_empty:
            exec_status = QueryExecutionStatus.EMPTY
            task.status = QueryTaskStatus.COMPLETED
        else:
            exec_status = QueryExecutionStatus.SUCCESS
            task.status = QueryTaskStatus.COMPLETED

        # Construct initial execution record
        record = QueryExecutionRecord(
            query_id=task.query_id,
            purpose=task.purpose,
            sub_question=task.sub_question,
            sql=sql,
            status=exec_status,
            row_count=len(rows) if rows else 0,
            rows=rows or [],
            findings=[],
            metrics={},
            execution_time_ms=execution_time_ms,
            cache_hit=cache_hit,
            error=exec_error,
        )

        # Extract structured, grounded evidence via EvidenceManager (Phase 4)
        from app.services.analysis.evidence_manager import EvidenceManager, InvestigationProgressEvaluator
        extracted_evidence = EvidenceManager.extract_evidence(record=record, task=task)
        for ev in extracted_evidence:
            state.add_evidence(ev)
            if ev.statement and ev.statement not in record.findings:
                record.findings.append(ev.statement)
            if ev.metric and ev.value is not None:
                record.metrics[ev.metric] = ev.value

        state.add_execution_record(record)
        state.query_results[task.query_id] = rows or []

        # Handle failure cascading to dependent tasks (Section 9)
        if is_failure and state.plan:
            for other_task in state.plan.query_tasks:
                if other_task.status == QueryTaskStatus.PENDING and task.query_id in other_task.depends_on:
                    other_task.status = QueryTaskStatus.BLOCKED
                    logger.info(
                        "Marking dependent query '%s' as BLOCKED due to failure of '%s'",
                        other_task.query_id,
                        task.query_id,
                    )

        # Synchronize task in plan
        if state.plan:
            for t in state.plan.query_tasks:
                if t.query_id == task.query_id:
                    t.status = task.status
                    break

        # Progress Evaluation and Unresolved Questions synchronization (Phase 4)
        progress = InvestigationProgressEvaluator.evaluate_progress(state)
        state.status = progress.completion_status

        # Evaluate active hypotheses if registered (Phase 6)
        if state.active_hypotheses:
            from app.services.analysis.hypothesis_manager import HypothesisManager
            state.active_hypotheses = HypothesisManager.evaluate_hypotheses(
                hypotheses=state.active_hypotheses,
                evidence=state.evidence,
                state=state,
            )
            # Update tested hypotheses mapping
            for h in state.active_hypotheses:
                state.tested_hypotheses[h.hypothesis_id] = (h.status == HypothesisStatus.SUPPORTED)

        return record

    @staticmethod
    def evaluate_investigation_status(state: InvestigationState) -> InvestigationStatus:
        """Evaluate stop conditions and determine overall InvestigationStatus."""
        if not state.plan or not state.plan.query_tasks:
            return InvestigationStatus.COMPLETED

        total_tasks = len(state.plan.query_tasks)
        completed_tasks = [t for t in state.plan.query_tasks if t.status == QueryTaskStatus.COMPLETED]
        failed_tasks = [t for t in state.plan.query_tasks if t.status == QueryTaskStatus.FAILED]
        blocked_tasks = [t for t in state.plan.query_tasks if t.status == QueryTaskStatus.BLOCKED]
        pending_tasks = [t for t in state.plan.query_tasks if t.status == QueryTaskStatus.PENDING]

        # Calculate completeness
        if total_tasks > 0:
            state.completeness_score = round(len(completed_tasks) / total_tasks, 2)

        # Check Condition 3: Budget reached
        if state.queries_executed >= state.max_queries:
            if len(completed_tasks) == total_tasks:
                return InvestigationStatus.COMPLETED
            elif len(completed_tasks) > 0:
                return InvestigationStatus.BUDGET_EXHAUSTED
            else:
                return InvestigationStatus.FAILED

        # Check Condition 2: All tasks completed
        if len(completed_tasks) == total_tasks:
            return InvestigationStatus.COMPLETED

        # Check if any tasks are still eligible to run
        has_runnable = any(
            not t.depends_on
            or all(any(c.query_id == dep for c in completed_tasks) for dep in t.depends_on)
            for t in pending_tasks
        )

        if pending_tasks and has_runnable:
            return InvestigationStatus.RUNNING

        # No runnable tasks remain
        if len(completed_tasks) > 0:
            if len(failed_tasks) > 0 or len(blocked_tasks) > 0 or len(pending_tasks) > 0:
                return InvestigationStatus.PARTIAL
            return InvestigationStatus.COMPLETED
        else:
            # No tasks succeeded
            return InvestigationStatus.FAILED

    @staticmethod
    def should_continue(state: InvestigationState) -> bool:
        """Determine whether the investigation loop should execute another query."""
        if state.status not in (
            InvestigationStatus.RUNNING,
            InvestigationStatus.IN_PROGRESS,
            InvestigationStatus.PENDING,
        ):
            return False

        if state.queries_executed >= state.max_queries:
            return False

        if state.reasoning_steps >= state.max_reasoning_steps:
            return False

        next_task = InvestigationEngine.select_next_task(state)
        return next_task is not None
