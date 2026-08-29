"""Data models for Adaptive Investigation, Multi-Query Planning, and Evidence Tracking.

Phase 2 Foundation:
Establishes typed models for investigative goal decomposition, separating Analytical Tasks
(what to determine/analyze) from Query Tasks (how to retrieve required data slices),
with explicit DAG dependencies, expected evidence contracts, and strict planning validation.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union
from pydantic import BaseModel, Field


class InvestigationMode(str, Enum):
    """Operational mode for analytical investigation."""
    DIRECT = "direct"              # Single direct SQL retrieval is sufficient
    EXPLORATORY = "exploratory"    # Multi-dimensional discovery and profiling
    ROOT_CAUSE = "root_cause"      # Deep-dive diagnostic investigating anomalies/drops
    COMPARATIVE = "comparative"    # Multi-period, cohort, or segment comparison
    DATA_AUDIT = "data_audit"      # Data quality, distribution, and completeness audit
    FORECASTING = "forecasting"    # Trend projection and scenario modeling


class QueryTaskStatus(str, Enum):
    """Lifecycle status of a query retrieval task."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class QueryExecutionStatus(str, Enum):
    """Outcome status of a query execution."""
    SUCCESS = "success"
    FAILED = "failed"
    EMPTY = "empty"
    CACHED = "cached"


class EvidenceType(str, Enum):
    """Classification category for extracted evidence."""
    NUMERIC = "numeric"
    CATEGORICAL = "categorical"
    TREND = "trend"
    COMPARISON = "comparison"
    RANKING = "ranking"
    OBSERVATION = "observation"
    ANOMALY = "anomaly"
    FACT = "fact"


class InvestigationStatus(str, Enum):
    """Overall lifecycle status of an investigation."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    # Backward-compatible lifecycle aliases
    NOT_STARTED = "not_started"
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    SUFFICIENT_EVIDENCE = "sufficient_evidence"
    MAX_QUERIES_REACHED = "max_queries_reached"


class PlanningValidationError(ValueError):
    """Raised when an InvestigationPlan fails structural or dependency validation."""
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


class QueryTask(BaseModel):
    """Represents an independent data retrieval task in the investigation workflow.
    
    Serves as the concrete data-fetching step supporting a parent AnalyticalTask.
    """
    query_id: str = Field(description="Unique identifier for this query task, e.g. 'q_1'")
    analytical_task_id: Optional[str] = Field(default=None, description="ID of parent AnalysisTask this query serves")
    purpose: str = Field(default="", description="Analytical purpose or rationale for this query")
    sub_question: str = Field(description="Natural language sub-question for SQL generation")
    required_metrics: List[str] = Field(default_factory=list, description="Target metrics or columns to compute")
    required_dimensions: List[str] = Field(default_factory=list, description="Target grouping dimensions")
    required_filters: List[str] = Field(default_factory=list, description="Target filter expressions or conditions")
    expected_grain: Optional[str] = Field(default=None, description="Expected grain/granularity, e.g. 'monthly', 'customer_id'")
    expected_columns: List[str] = Field(default_factory=list, description="Expected column names in output")
    expected_evidence: Optional[str] = Field(default=None, description="Expected factual evidence or findings produced by this query")
    depends_on: List[str] = Field(default_factory=list, description="List of query_ids that must complete before this task")
    priority: int = Field(default=1, ge=1, description="Execution priority (1 = highest)")
    status: QueryTaskStatus = Field(default=QueryTaskStatus.PENDING, description="Current execution status")
    can_be_skipped_if_answered: bool = Field(default=False, description="Whether this task can be skipped if prior evidence suffices")
    estimated_cost: float = Field(default=1.0, ge=0.0, description="Estimated computational cost or complexity")

    @classmethod
    def from_data_requirement(
        cls,
        req: Any,
        priority: int = 1,
        depends_on: Optional[List[str]] = None,
        can_be_skipped: bool = False,
        analytical_task_id: Optional[str] = None,
        expected_evidence: Optional[str] = None,
    ) -> "QueryTask":
        """Convert an existing DataRetrievalRequirement into a QueryTask."""
        req_id = getattr(req, "requirement_id", "q_1")
        purpose = getattr(req, "description", "")
        sub_q = getattr(req, "sub_question", "") or purpose
        metrics = list(getattr(req, "metrics", []))
        dimensions = list(getattr(req, "dimensions", []))
        filters = list(getattr(req, "filters", []))

        if depends_on is not None:
            resolved_deps = list(depends_on)
        else:
            req_deps = getattr(req, "depends_on", None) or getattr(req, "dependencies", None)
            resolved_deps = list(req_deps) if req_deps is not None else []

        resolved_analytical_task_id = analytical_task_id or getattr(req, "analytical_task_id", None)
        resolved_expected_evidence = expected_evidence or getattr(req, "expected_evidence", None)

        return cls(
            query_id=req_id,
            analytical_task_id=resolved_analytical_task_id,
            purpose=purpose,
            sub_question=sub_q,
            required_metrics=metrics,
            required_dimensions=dimensions,
            required_filters=filters,
            expected_evidence=resolved_expected_evidence,
            depends_on=resolved_deps,
            priority=priority,
            status=QueryTaskStatus.PENDING,
            can_be_skipped_if_answered=can_be_skipped,
        )

    def to_data_requirement(self) -> Any:
        """Convert this QueryTask into a DataRetrievalRequirement for backward compatibility."""
        from app.services.analysis.models import DataRetrievalRequirement
        return DataRetrievalRequirement(
            requirement_id=self.query_id,
            analytical_task_id=self.analytical_task_id,
            description=self.purpose or self.sub_question,
            sub_question=self.sub_question,
            expected_evidence=self.expected_evidence,
            metrics=self.required_metrics,
            dimensions=self.required_dimensions,
            filters=self.required_filters,
        )


class QueryExecutionRecord(BaseModel):
    """Represents the execution outcome and metadata of a single query."""
    query_id: str = Field(description="ID of the QueryTask executed")
    purpose: str = Field(default="", description="Purpose of this query")
    sub_question: str = Field(default="", description="Sub-question executed")
    sql: str = Field(default="", description="SQL statement generated and executed")
    status: QueryExecutionStatus = Field(default=QueryExecutionStatus.SUCCESS, description="Execution outcome status")
    row_count: int = Field(default=0, ge=0, description="Number of rows returned")
    rows: List[Dict[str, Any]] = Field(default_factory=list, description="Retrieved rows or data sample")
    findings: List[str] = Field(default_factory=list, description="Analytical findings extracted from this query")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Computed statistical or aggregated metrics")
    execution_time_ms: float = Field(default=0.0, ge=0.0, description="Execution duration in milliseconds")
    cache_hit: bool = Field(default=False, description="Whether the result was served from cache")
    error: Optional[str] = Field(default=None, description="Error message if execution failed")


class EvidenceItem(BaseModel):
    """Represents a verified fact or evidence data point extracted during investigation."""
    evidence_id: str = Field(description="Unique ID for this evidence item, e.g. 'ev_1'")
    source_query_id: Optional[str] = Field(default=None, description="QueryTask ID that produced this evidence")
    statement: str = Field(description="Natural language statement of the verified fact or finding")
    value: Optional[Any] = Field(default=None, description="Structured value (scalar, dict, list, or metric value)")
    metric: Optional[str] = Field(default=None, description="Associated primary metric name if applicable")
    dimensions: Dict[str, Any] = Field(default_factory=dict, description="Associated dimensional context")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0")
    verified: bool = Field(default=True, description="Whether this evidence has been verified against raw data")
    evidence_type: EvidenceType = Field(default=EvidenceType.FACT, description="Category of evidence")
    derivation_method: Optional[str] = Field(default="raw_observed", description="Method used to derive this evidence (e.g. 'raw_observed', 'deterministic_ranking', 'comparison_delta', 'chronological_trend')")


class HypothesisStatus(str, Enum):
    """Lifecycle and evaluation status of an investigative hypothesis."""
    PROPOSED = "proposed"
    TESTING = "testing"
    SUPPORTED = "supported"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class Hypothesis(BaseModel):
    """Represents an investigative hypothesis with evidence-based status tracking."""
    hypothesis_id: str = Field(description="Unique identifier for this hypothesis, e.g. 'h_1'")
    statement: str = Field(description="Hypothesis assertion statement, e.g. 'Revenue decline is primarily volume-driven'")
    status: HypothesisStatus = Field(default=HypothesisStatus.PROPOSED, description="Current test evaluation status")
    supporting_evidence: List[str] = Field(default_factory=list, description="List of evidence IDs or statements supporting this hypothesis")
    contradicting_evidence: List[str] = Field(default_factory=list, description="List of evidence IDs or statements contradicting this hypothesis")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Confidence score in the evaluation outcome (0.0 to 1.0)")
    required_evidence: List[str] = Field(default_factory=list, description="Evidence descriptions required to evaluate this hypothesis")
    required_analysis_tasks: List[str] = Field(default_factory=list, description="Analysis tasks associated with testing this hypothesis")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Computed quantitative metrics (e.g. contribution_pct, delta)")
    rationale: Optional[str] = Field(default=None, description="Detailed explanation of the evaluation outcome")


class ValidationIssueType(str, Enum):
    """Classification of cross-query consistency and reconciliation issues."""
    RECONCILIATION = "reconciliation"
    METRIC_CONFLICT = "metric_conflict"
    TIME_MISMATCH = "time_mismatch"
    DIMENSION_MISMATCH = "dimension_mismatch"
    DUPLICATE_EVIDENCE = "duplicate_evidence"


class ValidationSeverity(str, Enum):
    """Severity level of an identified consistency issue."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class ValidationIssueStatus(str, Enum):
    """Resolution status of a validation issue."""
    OPEN = "open"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class ValidationIssue(BaseModel):
    """Represents a detected contradiction or consistency mismatch across queries."""
    issue_id: str = Field(description="Unique ID for this issue, e.g. 'iss_rec_1'")
    type: ValidationIssueType = Field(description="Type of validation issue")
    severity: ValidationSeverity = Field(default=ValidationSeverity.WARNING, description="Issue severity")
    query_ids: List[str] = Field(default_factory=list, description="IDs of queries involved in the inconsistency")
    description: str = Field(description="Human-readable description of the discrepancy")
    expected: Optional[Any] = Field(default=None, description="Expected value or baseline quantity")
    actual: Optional[Any] = Field(default=None, description="Actual observed value or sum")
    status: ValidationIssueStatus = Field(default=ValidationIssueStatus.OPEN, description="Current resolution status")


def validate_investigation_plan(plan: "InvestigationPlan", raise_on_error: bool = False) -> List[str]:
    """Validate an InvestigationPlan against Phase 2 structural and relational rules:

    Rule 1 (Unique ID): Every QueryTask must have a unique, non-empty query_id.
    Rule 2 (Parent Task Reference): If analytical_task_id is specified, it must exist in analysis_tasks.
    Rule 3 (Valid Dependencies): All dependencies in QueryTask.depends_on must reference existing QueryTasks.
    Rule 4 (No Cycles): No cyclic dependencies (e.g. Q1 -> Q2 -> Q1) may exist among query tasks or analysis tasks.
    Rule 5 (Completeness): Every QueryTask must have non-empty purpose and sub_question.
    Rule 6 (Semantic Deduplication): No duplicate query tasks with identical normalized purpose and sub-question.
    """
    errors: List[str] = []

    # Rule 1: Unique query_id
    seen_query_ids: Set[str] = set()
    for q in plan.query_tasks:
        if not q.query_id or not q.query_id.strip():
            errors.append("QueryTask has an empty query_id")
        elif q.query_id in seen_query_ids:
            errors.append(f"Duplicate query_id detected: '{q.query_id}'")
        seen_query_ids.add(q.query_id)

    # Analysis task IDs for Rule 2 & Rule 3
    analysis_task_ids = {t.task_id for t in plan.analysis_tasks if getattr(t, "task_id", None)}

    # Rule 2: Valid analytical_task_id reference
    if plan.analysis_tasks:
        for q in plan.query_tasks:
            if q.analytical_task_id and q.analytical_task_id not in analysis_task_ids:
                errors.append(
                    f"QueryTask '{q.query_id}' references unknown analytical_task_id '{q.analytical_task_id}'"
                )

    # Rule 3: Valid depends_on references for QueryTasks
    for q in plan.query_tasks:
        for dep in q.depends_on:
            if dep not in seen_query_ids:
                errors.append(f"QueryTask '{q.query_id}' depends on unknown query_id '{dep}'")

    # Valid depends_on references for AnalysisTasks
    for t in plan.analysis_tasks:
        t_deps = getattr(t, "depends_on", []) or getattr(t, "dependencies", [])
        for dep in t_deps:
            if dep not in analysis_task_ids:
                errors.append(f"AnalysisTask '{getattr(t, 'task_id', '')}' depends on unknown task_id '{dep}'")

    # Rule 4: Cycle detection on QueryTasks (DFS)
    q_adj: Dict[str, List[str]] = {q.query_id: list(q.depends_on) for q in plan.query_tasks if q.query_id}
    visited: Dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=visited

    def has_q_cycle(node: str, path: List[str]) -> Optional[List[str]]:
        visited[node] = 1
        for neighbor in q_adj.get(node, []):
            if neighbor not in q_adj:
                continue
            if visited.get(neighbor, 0) == 1:
                return path + [neighbor]
            if visited.get(neighbor, 0) == 0:
                cycle_res = has_q_cycle(neighbor, path + [neighbor])
                if cycle_res:
                    return cycle_res
        visited[node] = 2
        return None

    for q_id in q_adj:
        if visited.get(q_id, 0) == 0:
            cycle = has_q_cycle(q_id, [q_id])
            if cycle:
                errors.append(f"Cyclic dependency detected among query tasks: {' -> '.join(cycle)}")
                break

    # Also detect cycles in AnalysisTasks
    if plan.analysis_tasks:
        t_adj: Dict[str, List[str]] = {
            t.task_id: list(getattr(t, "depends_on", []) or getattr(t, "dependencies", []))
            for t in plan.analysis_tasks
            if getattr(t, "task_id", None)
        }
        t_visited: Dict[str, int] = {}

        def has_t_cycle(node: str, path: List[str]) -> Optional[List[str]]:
            t_visited[node] = 1
            for neighbor in t_adj.get(node, []):
                if neighbor not in t_adj:
                    continue
                if t_visited.get(neighbor, 0) == 1:
                    return path + [neighbor]
                if t_visited.get(neighbor, 0) == 0:
                    cycle_res = has_t_cycle(neighbor, path + [neighbor])
                    if cycle_res:
                        return cycle_res
            t_visited[node] = 2
            return None

        for t_id in t_adj:
            if t_visited.get(t_id, 0) == 0:
                cycle = has_t_cycle(t_id, [t_id])
                if cycle:
                    errors.append(f"Cyclic dependency detected among analysis tasks: {' -> '.join(cycle)}")
                    break

    # Rule 5: Non-empty purpose and sub_question
    for q in plan.query_tasks:
        if not (q.purpose and q.purpose.strip()):
            errors.append(f"QueryTask '{q.query_id}' must have a non-empty purpose")
        if not (q.sub_question and q.sub_question.strip()):
            errors.append(f"QueryTask '{q.query_id}' must have a non-empty sub_question")

    # Rule 6: No semantically duplicate QueryTasks (normalized purpose & sub_question)
    seen_signatures: Set[tuple] = set()
    for q in plan.query_tasks:
        sig = (q.purpose.strip().lower(), q.sub_question.strip().lower())
        if sig in seen_signatures:
            errors.append(
                f"Duplicate query task detected with identical purpose and sub_question: '{q.sub_question}'"
            )
        seen_signatures.add(sig)

    if raise_on_error and errors:
        raise PlanningValidationError(errors)

    return errors


class InvestigationPlan(BaseModel):
    """Holistic analytical investigation plan for multi-step reasoning and data retrieval.
    
    Coordinates the hierarchy:
    InvestigationPlan -> AnalysisTask[] (what to analyze) -> QueryTask[] (what queries to run).
    """
    question: str = Field(description="Primary user question under investigation")
    goal: str = Field(default="", description="Analytical objective of the investigation")
    investigation_mode: InvestigationMode = Field(default=InvestigationMode.EXPLORATORY, description="Mode of investigation")
    analysis_tasks: List[Any] = Field(default_factory=list, description="Structured analytical tasks decomposing the goal")
    query_tasks: List[QueryTask] = Field(default_factory=list, description="Ordered or DAG query retrieval tasks")
    hypotheses: List[str] = Field(default_factory=list, description="Initial hypotheses to explore or test")
    expected_insights: List[str] = Field(default_factory=list, description="Key insights expected from the investigation")
    max_queries: int = Field(default=5, ge=1, description="Maximum number of query executions allowed")
    max_reasoning_steps: int = Field(default=10, ge=1, description="Maximum reasoning iterations allowed")
    stop_conditions: List[str] = Field(default_factory=list, description="Conditions upon which to terminate early")

    def get_sub_questions(self) -> List[str]:
        """Extract ordered sub-questions for SQL execution."""
        return [task.sub_question for task in self.query_tasks if task.sub_question]

    def get_pending_tasks(self) -> List[QueryTask]:
        """Return all query tasks that have not yet been executed."""
        return [t for t in self.query_tasks if t.status == QueryTaskStatus.PENDING]

    def get_next_runnable_task(self, completed_ids: Optional[set] = None) -> Optional[QueryTask]:
        """Return the next pending task whose dependencies are satisfied."""
        if completed_ids is None:
            completed_ids = {t.query_id for t in self.query_tasks if t.status == QueryTaskStatus.COMPLETED}
        
        indexed_tasks = list(enumerate(self.query_tasks))
        for idx, task in sorted(indexed_tasks, key=lambda item: (item[1].priority, item[0])):
            if task.status == QueryTaskStatus.PENDING:
                if not task.depends_on or all(dep in completed_ids for dep in task.depends_on):
                    return task
        return None

    def get_query_tasks_for_analysis_task(self, task_id: str) -> List[QueryTask]:
        """Retrieve all QueryTasks associated with a specific AnalysisTask."""
        return [q for q in self.query_tasks if q.analytical_task_id == task_id]

    def validate_plan(self, raise_on_error: bool = False) -> List[str]:
        """Validate this InvestigationPlan against all 6 planning rules."""
        return validate_investigation_plan(self, raise_on_error=raise_on_error)

    @property
    def is_valid(self) -> bool:
        """Boolean indicator of plan validity."""
        return len(self.validate_plan(raise_on_error=False)) == 0

    @classmethod
    def from_analysis_plan(
        cls,
        plan: Any,
        investigation_mode: InvestigationMode = InvestigationMode.EXPLORATORY,
        max_queries: int = 5,
        max_reasoning_steps: int = 10,
    ) -> "InvestigationPlan":
        """Construct a validated InvestigationPlan from an existing AnalysisPlan.
        
        Prioritizes canonical query_tasks when present, without positional parent-mapping
        or fabricated sequential dependencies.
        """
        from app.services.analysis.models import AnalysisTask

        # 1. Reconstruct or copy AnalysisTasks
        source_tasks = getattr(plan, "tasks", []) or getattr(plan, "analysis_tasks", []) or []
        analysis_tasks: List[AnalysisTask] = []
        for i, t in enumerate(source_tasks):
            if isinstance(t, AnalysisTask):
                analysis_tasks.append(t)
            elif isinstance(t, dict):
                analysis_tasks.append(AnalysisTask(**t))
            else:
                analysis_tasks.append(
                    AnalysisTask(
                        task_id=getattr(t, "task_id", f"task_{i+1}"),
                        name=getattr(t, "name", f"Task {i+1}"),
                        objective=getattr(t, "objective", None) or getattr(t, "description", ""),
                        description=getattr(t, "description", ""),
                        operation=getattr(t, "operation", None),
                        dependencies=getattr(t, "dependencies", []),
                        depends_on=getattr(t, "depends_on", []),
                        data_requirement_ids=getattr(t, "data_requirement_ids", []),
                        required_query_tasks=getattr(t, "required_query_tasks", []),
                        priority=getattr(t, "priority", 1),
                        expected_insights=getattr(t, "expected_insights", []),
                    )
                )

        # 2. Extract QueryTasks: prefer canonical query_tasks if present
        source_query_tasks = getattr(plan, "query_tasks", []) or []
        query_tasks: List[QueryTask] = []

        if source_query_tasks:
            for q in source_query_tasks:
                if isinstance(q, QueryTask):
                    query_tasks.append(q)
                elif isinstance(q, dict):
                    query_tasks.append(QueryTask(**q))
        else:
            # Fallback to converting data_requirements (backward compatibility)
            data_reqs = getattr(plan, "data_requirements", []) or []
            for i, req in enumerate(data_reqs):
                req_id = getattr(req, "requirement_id", f"req_{i+1}")
                # Semantic parent AnalysisTask lookup only - NO positional mapping
                parent_task_id = getattr(req, "analytical_task_id", None)
                if not parent_task_id:
                    for t in analysis_tasks:
                        if req_id in (t.data_requirement_ids or t.required_query_tasks):
                            parent_task_id = t.task_id
                            break

                req_deps = getattr(req, "depends_on", None) or getattr(req, "dependencies", None)
                explicit_deps = list(req_deps) if req_deps is not None else []
                exp_ev = getattr(req, "expected_evidence", None)

                q_task = QueryTask.from_data_requirement(
                    req=req,
                    priority=getattr(req, "priority", i + 1),
                    depends_on=explicit_deps,
                    analytical_task_id=parent_task_id,
                    expected_evidence=exp_ev,
                )
                query_tasks.append(q_task)

        # 3. Synchronize required_query_tasks on AnalysisTasks where explicitly linked
        for q in query_tasks:
            if q.analytical_task_id:
                for t in analysis_tasks:
                    if t.task_id == q.analytical_task_id:
                        if q.query_id not in t.required_query_tasks:
                            t.required_query_tasks.append(q.query_id)
                        if q.query_id not in t.data_requirement_ids:
                            t.data_requirement_ids.append(q.query_id)

        # 4. If no analysis_tasks were present in plan, create a default overarching AnalysisTask
        if not analysis_tasks and query_tasks:
            analysis_tasks.append(
                AnalysisTask(
                    task_id="task_1",
                    name="Primary Data Retrieval & Analysis",
                    objective=getattr(plan, "analysis_goal", "") or getattr(plan, "question", ""),
                    description=getattr(plan, "analysis_goal", "") or getattr(plan, "question", ""),
                    required_query_tasks=[q.query_id for q in query_tasks],
                    data_requirement_ids=[q.query_id for q in query_tasks],
                )
            )
            for q in query_tasks:
                if not q.analytical_task_id:
                    q.analytical_task_id = "task_1"

        return cls(
            question=getattr(plan, "question", ""),
            goal=getattr(plan, "analysis_goal", "") or getattr(plan, "goal", ""),
            investigation_mode=investigation_mode,
            analysis_tasks=analysis_tasks,
            query_tasks=query_tasks,
            hypotheses=getattr(plan, "hypotheses", []),
            expected_insights=getattr(plan, "expected_insights", []),
            max_queries=max_queries,
            max_reasoning_steps=max_reasoning_steps,
            stop_conditions=["sufficient_evidence", "confidence_threshold_reached"],
        )

    def to_analysis_plan(self) -> Any:
        """Convert this InvestigationPlan into an AnalysisPlan for backward compatibility."""
        from app.services.analysis.models import AnalysisPlan, AnalysisTask
        from app.agent.semantic.models import AnalysisLevel, AnalysisOperation
        from app.utils.helpers import AnalysisType

        data_reqs = [t.to_data_requirement() for t in self.query_tasks]
        tasks = list(self.analysis_tasks) if self.analysis_tasks else [
            AnalysisTask(
                task_id=f"task_{i+1}",
                name=t.purpose or f"Task {i+1}",
                operation=AnalysisOperation.AGGREGATE,
                description=t.sub_question,
                required_query_tasks=[t.query_id],
                data_requirement_ids=[t.query_id],
            )
            for i, t in enumerate(self.query_tasks)
        ]

        return AnalysisPlan(
            question=self.question,
            analysis_required=True,
            analysis_level=AnalysisLevel.INSIGHT,
            analysis_type=AnalysisType.EXPLORATORY_ANALYSIS,
            analysis_goal=self.goal or self.question,
            tasks=tasks,
            data_requirements=data_reqs,
            expected_insights=self.expected_insights,
            requires_multi_step=len(data_reqs) > 1,
            source="investigation_plan_converter",
        )


class InvestigationState(BaseModel):
    """Complete runtime state of an adaptive data investigation."""
    plan: Optional[InvestigationPlan] = Field(default=None, description="Active investigation plan")
    current_query_task: Optional[QueryTask] = Field(default=None, description="The QueryTask currently being investigated")
    completed_queries: List[QueryExecutionRecord] = Field(default_factory=list, description="History of executed queries")
    query_results: Dict[str, Any] = Field(default_factory=dict, description="Retrieved rows mapped by query_id")
    evidence: List[EvidenceItem] = Field(default_factory=list, description="Accumulated evidence items")
    known_facts: List[str] = Field(default_factory=list, description="Established facts derived from evidence")
    unresolved_questions: List[str] = Field(default_factory=list, description="Remaining unresolved sub-questions")
    active_hypotheses: List[Hypothesis] = Field(default_factory=list, description="Structured hypotheses being investigated")
    hypotheses: List[str] = Field(default_factory=list, description="Active working hypotheses strings")
    tested_hypotheses: Dict[str, bool] = Field(default_factory=dict, description="Tested hypotheses mapping to outcome")
    validation_issues: List[ValidationIssue] = Field(default_factory=list, description="Cross-query consistency issues")
    findings: List[str] = Field(default_factory=list, description="Synthesized analytical findings")
    task_completion: float = Field(default=0.0, ge=0.0, le=1.0, description="Fraction of required query tasks completed (0.0 - 1.0)")
    evidence_coverage: float = Field(default=0.0, ge=0.0, le=1.0, description="Fraction of expected evidence collected and verified (0.0 - 1.0)")
    completeness_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Assessment of question completeness (0.0 - 1.0)")
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Overall confidence in accumulated evidence (0.0 - 1.0)")
    queries_executed: int = Field(default=0, ge=0, description="Count of queries executed so far")
    max_queries: int = Field(default=5, ge=1, description="Budget cap on maximum query executions")
    reasoning_steps: int = Field(default=0, ge=0, description="Count of reasoning steps taken")
    max_reasoning_steps: int = Field(default=10, ge=1, description="Budget cap on maximum reasoning iterations")
    status: InvestigationStatus = Field(default=InvestigationStatus.NOT_STARTED, description="Current investigation status")

    def add_hypothesis(self, hyp: Hypothesis) -> None:
        """Add or update an active hypothesis."""
        for i, existing in enumerate(self.active_hypotheses):
            if existing.hypothesis_id == hyp.hypothesis_id:
                self.active_hypotheses[i] = hyp
                return
        self.active_hypotheses.append(hyp)
        if hyp.statement not in self.hypotheses:
            self.hypotheses.append(hyp.statement)

    def add_execution_record(self, record: QueryExecutionRecord) -> None:
        """Record a completed query execution and update counters."""
        self.completed_queries.append(record)
        self.queries_executed = len(self.completed_queries)
        if record.findings:
            for f in record.findings:
                if f not in self.findings:
                    self.findings.append(f)
                if f not in self.known_facts:
                    self.known_facts.append(f)
        if self.queries_executed >= self.max_queries:
            if self.status == InvestigationStatus.IN_PROGRESS:
                self.status = InvestigationStatus.MAX_QUERIES_REACHED
            elif self.status == InvestigationStatus.RUNNING:
                self.status = InvestigationStatus.BUDGET_EXHAUSTED

    def add_evidence(self, item: EvidenceItem) -> None:
        """Record an evidence item and update known facts and confidence."""
        self.evidence.append(item)
        if item.statement and item.statement not in self.known_facts:
            self.known_facts.append(item.statement)
        # Update rolling confidence score
        if self.evidence:
            self.confidence_score = round(sum(e.confidence for e in self.evidence) / len(self.evidence), 2)
        else:
            self.confidence_score = 0.0

    def is_complete(self) -> bool:
        """Determine whether the investigation has reached completion or stop criteria."""
        if self.status in (
            InvestigationStatus.COMPLETED,
            InvestigationStatus.PARTIAL,
            InvestigationStatus.BUDGET_EXHAUSTED,
            InvestigationStatus.SUFFICIENT_EVIDENCE,
            InvestigationStatus.MAX_QUERIES_REACHED,
            InvestigationStatus.FAILED,
        ):
            return True
        if self.completeness_score >= 1.0:
            return True
        if self.queries_executed >= self.max_queries:
            return True
        if self.reasoning_steps >= self.max_reasoning_steps:
            return True
        return False
