"""Data models for the Analysis Planning and Execution layer."""
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.agent.semantic.models import AnalysisLevel, AnalysisOperation
from app.utils.helpers import AnalysisType


class ComputationType(str, Enum):
    TOTAL = "total"
    PERIODIC_AGGREGATE = "periodic_aggregate"
    GROWTH_RATE = "growth_rate"
    PEAK_AND_TROUGH = "peak_and_trough"
    OUTLIER_DETECTION = "outlier_detection"
    CORRELATION = "correlation"
    DISTRIBUTION_SPREAD = "distribution_spread"
    SEGMENT_RANKING = "segment_ranking"
    HYPOTHESIS_TEST = "hypothesis_test"
    DATA_QUALITY_AUDIT = "data_quality_audit"
    FORECAST_TREND = "forecast_trend"


class DataRetrievalRequirement(BaseModel):
    """Specific dataset or aggregate that must be fetched from the database."""
    requirement_id: str = Field(description="Unique ID for this retrieval requirement, e.g. 'req_1'")
    analytical_task_id: Optional[str] = Field(default=None, description="Parent analytical task ID if applicable")
    description: str = Field(description="Human-readable description of what data is needed")
    sub_question: str = Field(description="Target sub-question for SQL generation")
    expected_evidence: Optional[str] = Field(default=None, description="Target concrete evidence produced by this query")
    entity: Optional[str] = Field(default=None, description="Primary database table/entity")
    metrics: List[str] = Field(default_factory=list, description="Target metrics/columns")
    dimensions: List[str] = Field(default_factory=list, description="Target grouping dimensions")
    filters: List[str] = Field(default_factory=list, description="Target filter expressions")
    time_expressions: List[str] = Field(default_factory=list, description="Target time constraints")
    aggregations: List[str] = Field(default_factory=list, description="Target aggregation functions")
    limit: Optional[int] = Field(default=None, description="Row limit if ranking")
    sort_direction: Optional[str] = Field(default=None, description="Sort direction (DESC/ASC)")


class AnalysisTask(BaseModel):
    """An analytical step to perform on retrieved data or prior task outputs."""
    task_id: str = Field(description="Unique ID for this task, e.g. 'task_1'")
    name: str = Field(description="Short name for the analytical operation")
    objective: Optional[str] = Field(default=None, description="Analytical objective / target question to answer")
    operation: AnalysisOperation = Field(default=AnalysisOperation.AGGREGATE, description="Core analysis operation category")
    analysis_type: Optional[str] = Field(default=None, description="Category of analytical reasoning")
    description: str = Field(default="", description="Detailed explanation of what this step computes or checks")
    computation_type: Optional[ComputationType] = Field(default=None, description="Type of statistical/analytical computation")
    data_requirement_ids: List[str] = Field(default_factory=list, description="Data requirement IDs needed for this task")
    required_query_tasks: List[str] = Field(default_factory=list, description="QueryTask IDs required for this analytical task")
    dependencies: List[str] = Field(default_factory=list, description="Task IDs that must execute before this task")
    depends_on: List[str] = Field(default_factory=list, description="Task IDs that must execute before this task (alias)")
    priority: int = Field(default=1, ge=1, description="Analytical priority")
    expected_insights: List[str] = Field(default_factory=list, description="Insights expected from this analytical step")
    status: str = Field(default="pending", description="Task execution status: pending, completed, failed")

    def model_post_init(self, __context: Any) -> None:
        """Ensure objective, dependencies, and required_query_tasks synchronize gracefully."""
        if not self.objective:
            self.objective = self.description or self.name
        if not self.dependencies and self.depends_on:
            self.dependencies = list(self.depends_on)
        elif not self.depends_on and self.dependencies:
            self.depends_on = list(self.dependencies)
        if not self.required_query_tasks and self.data_requirement_ids:
            self.required_query_tasks = list(self.data_requirement_ids)
        elif not self.data_requirement_ids and self.required_query_tasks:
            self.data_requirement_ids = list(self.required_query_tasks)



class AnalysisPlan(BaseModel):
    """Complete analytical blueprint separating Analysis Planning from SQL Generation."""
    question: str = Field(description="Original user question")
    analysis_required: bool = Field(default=True, description="Whether analytical reasoning is needed")
    analysis_level: AnalysisLevel = Field(default=AnalysisLevel.INSIGHT, description="Level of analysis")
    analysis_type: AnalysisType = Field(default=AnalysisType.EXPLORATORY_ANALYSIS, description="Analytical intent category")
    analysis_goal: str = Field(description="Primary analytical objective")
    tasks: List[AnalysisTask] = Field(default_factory=list, description="Ordered or DAG analytical tasks (AnalysisTask[])")
    query_tasks: List[Any] = Field(default_factory=list, description="Canonical QueryTasks for database retrieval")
    data_requirements: List[DataRetrievalRequirement] = Field(default_factory=list, description="Compatibility DataRetrievalRequirements for SQL planner")
    hypotheses: List[str] = Field(default_factory=list, description="Initial hypotheses to explore or test")
    expected_insights: List[str] = Field(default_factory=list, description="Key insights expected from the analysis")
    constraints: List[str] = Field(default_factory=list, description="Analytical or data constraints")
    requires_multi_step: bool = Field(default=False, description="Whether multiple queries/steps are needed")
    max_queries: int = Field(default=5, description="Maximum queries budget")
    max_reasoning_steps: int = Field(default=10, description="Maximum reasoning steps")
    source: str = Field(default="analysis_planner", description="Planner origin")

    def model_post_init(self, __context: Any) -> None:
        """Synchronize canonical query_tasks and compatibility data_requirements cleanly."""
        from app.services.analysis.investigation_models import QueryTask

        # 1. If query_tasks is populated, generate compatibility data_requirements
        if self.query_tasks and not self.data_requirements:
            self.data_requirements = [
                q.to_data_requirement() if hasattr(q, "to_data_requirement") else QueryTask(**q).to_data_requirement()
                for q in self.query_tasks
            ]
        # 2. If only data_requirements is provided, construct canonical query_tasks
        elif self.data_requirements and not self.query_tasks:
            derived_qtasks: List[QueryTask] = []
            for i, req in enumerate(self.data_requirements):
                req_id = getattr(req, "requirement_id", f"req_{i+1}")
                # Explicit semantic link only
                parent_task_id = getattr(req, "analytical_task_id", None)
                if not parent_task_id:
                    for t in self.tasks:
                        if req_id in (t.data_requirement_ids or t.required_query_tasks):
                            parent_task_id = t.task_id
                            break

                req_deps = getattr(req, "depends_on", None) or getattr(req, "dependencies", None)
                explicit_deps = list(req_deps) if req_deps is not None else []
                exp_ev = getattr(req, "expected_evidence", None)

                derived_qtasks.append(
                    QueryTask.from_data_requirement(
                        req=req,
                        priority=getattr(req, "priority", i + 1),
                        depends_on=explicit_deps,
                        analytical_task_id=parent_task_id,
                        expected_evidence=exp_ev,
                    )
                )
            self.query_tasks = derived_qtasks

        # 3. Synchronize required_query_tasks on AnalysisTasks where explicitly linked
        if self.query_tasks and self.tasks:
            for q in self.query_tasks:
                q_id = getattr(q, "query_id", "")
                parent_id = getattr(q, "analytical_task_id", None)
                if parent_id and q_id:
                    for t in self.tasks:
                        if t.task_id == parent_id:
                            if q_id not in t.required_query_tasks:
                                t.required_query_tasks.append(q_id)
                            if q_id not in t.data_requirement_ids:
                                t.data_requirement_ids.append(q_id)

    def get_sub_questions(self) -> List[str]:
        """Convert canonical query tasks (or data requirements) into ordered sub-questions."""
        if self.query_tasks:
            return [getattr(q, "sub_question", "") for q in self.query_tasks if getattr(q, "sub_question", "")]
        return [req.sub_question for req in self.data_requirements if req.sub_question]

    def to_investigation_plan(
        self,
        investigation_mode: Optional["InvestigationMode"] = None,
        max_queries: Optional[int] = None,
        max_reasoning_steps: Optional[int] = None,
    ) -> "InvestigationPlan":
        """Convert this AnalysisPlan to an InvestigationPlan using canonical QueryTasks."""
        from app.services.analysis.investigation_models import InvestigationPlan, InvestigationMode
        mode = investigation_mode or InvestigationMode.EXPLORATORY
        budget_q = max_queries if max_queries is not None else self.max_queries
        budget_r = max_reasoning_steps if max_reasoning_steps is not None else self.max_reasoning_steps
        return InvestigationPlan.from_analysis_plan(
            self,
            investigation_mode=mode,
            max_queries=budget_q,
            max_reasoning_steps=budget_r,
        )



class AnalysisTaskResult(BaseModel):
    """Result of a single analytical computation task."""
    task_id: str
    name: str
    status: str = "completed"
    computed_metrics: Dict[str, Any] = Field(default_factory=dict)
    findings: List[str] = Field(default_factory=list)
    anomalies: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class AnalysisExecutionResult(BaseModel):
    """Overall result of executing an AnalysisPlan."""
    plan: AnalysisPlan
    task_results: List[AnalysisTaskResult] = Field(default_factory=list)
    all_findings: List[str] = Field(default_factory=list)
    computed_summary: Dict[str, Any] = Field(default_factory=dict)
    raw_data: List[Dict[str, Any]] = Field(default_factory=list)
    success: bool = True
    error: Optional[str] = None


class AnalysisResult(BaseModel):
    """Unified, structured analytical result unifying findings, metrics, evidence, and limitations."""
    analysis_type: str = Field(description="Analytical category, e.g. root_cause, trend, comparison, correlation, data_quality, etc.")
    goal: str = Field(default="", description="Analytical objective or primary question goal")
    findings: List[str] = Field(default_factory=list, description="Primary verified analytical conclusions (e.g. 'Sales decreased 18%')")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Key computed numerical and statistical metrics")
    evidence: List[str] = Field(default_factory=list, description="Concrete data points supporting findings (e.g. 'Q4 sales = 820K, Q3 sales = 1.0M')")
    warnings: List[str] = Field(default_factory=list, description="Quality, variance, or data warnings")
    limitations: List[str] = Field(default_factory=list, description="Analytical boundaries and what cannot be concluded from the data")
    confidence: float = Field(default=1.0, description="Confidence score between 0.0 and 1.0 based on data quality and grounding")
    recommendations: List[str] = Field(default_factory=list, description="Actionable next steps or suggested drilldown investigations")
    chart_hint: Optional[Dict[str, Any]] = Field(default=None, description="Recommended chart type and visualization configuration")

    @classmethod
    def from_analytics_and_insights(
        cls,
        analytics_result: Optional[Any] = None,
        insight_result: Optional[Any] = None,
        analysis_plan: Optional[Any] = None,
        query_spec: Optional[Any] = None,
        confidence: float = 1.0,
    ) -> "AnalysisResult":
        """Construct a unified AnalysisResult from analytics results, insights, and query specs."""
        analysis_type = "exploratory"
        goal = ""
        findings = []
        metrics: Dict[str, Any] = {}
        evidence = []
        warnings = []
        limitations = []

        if query_spec:
            analysis_type = (
                query_spec.analysis_type.value
                if hasattr(query_spec.analysis_type, "value")
                else str(query_spec.analysis_type)
            )
            goal = getattr(query_spec, "analysis_goal", "") or getattr(query_spec, "raw_question", "")

        if analysis_plan:
            if hasattr(analysis_plan, "analysis_goal") and analysis_plan.analysis_goal:
                goal = analysis_plan.analysis_goal
            if hasattr(analysis_plan, "expected_insights"):
                limitations.extend(getattr(analysis_plan, "constraints", []))

        if analytics_result:
            if hasattr(analytics_result, "analytical_findings") and analytics_result.analytical_findings:
                findings.extend(analytics_result.analytical_findings)
            if hasattr(analytics_result, "task_results") and analytics_result.task_results:
                for task_res in analytics_result.task_results:
                    c_metrics = task_res.get("computed_metrics", {}) if isinstance(task_res, dict) else getattr(task_res, "computed_metrics", {})
                    if c_metrics:
                        metrics.update(c_metrics)
                    t_findings = task_res.get("findings", []) if isinstance(task_res, dict) else getattr(task_res, "findings", [])
                    if t_findings:
                        findings.extend(t_findings)
            if hasattr(analytics_result, "dataset") and analytics_result.dataset:
                metrics["total_rows"] = analytics_result.dataset.row_count
                metrics["column_count"] = analytics_result.dataset.column_count
            if hasattr(analytics_result, "numeric_stats") and analytics_result.numeric_stats:
                for col_name, nstat in analytics_result.numeric_stats.items():
                    metrics[f"{col_name}_mean"] = getattr(nstat, "mean", None)
                    if hasattr(nstat, "sum_value") and getattr(nstat, "sum_value") is not None:
                        metrics[f"{col_name}_sum"] = getattr(nstat, "sum_value")
                    metrics[f"{col_name}_min"] = getattr(nstat, "min_value", None)
                    metrics[f"{col_name}_max"] = getattr(nstat, "max_value", None)
                    evidence.append(f"{col_name}: min={getattr(nstat, 'min_value', None)}, max={getattr(nstat, 'max_value', None)}, avg={getattr(nstat, 'mean', None)}")

        if insight_result and hasattr(insight_result, "insights"):
            for item in insight_result.insights:
                sev = getattr(item, "severity", None)
                sev_val = sev.value if hasattr(sev, "value") else str(sev).lower()
                msg = getattr(item, "message", "")
                if sev_val in ("critical", "warning"):
                    warnings.append(msg)
                else:
                    if msg not in findings:
                        findings.append(msg)

        # Remove duplicate findings / evidence preserving order
        dedup_findings = list(dict.fromkeys(findings))
        dedup_evidence = list(dict.fromkeys(evidence))
        dedup_warnings = list(dict.fromkeys(warnings))

        return cls(
            analysis_type=analysis_type,
            goal=goal,
            findings=dedup_findings,
            metrics=metrics,
            evidence=dedup_evidence,
            warnings=dedup_warnings,
            limitations=limitations,
            confidence=round(confidence, 2),
        )


# Re-export Adaptive Investigation Foundation Models
from app.services.analysis.investigation_models import (
    InvestigationMode,
    QueryTaskStatus,
    QueryExecutionStatus,
    EvidenceType,
    InvestigationStatus,
    PlanningValidationError,
    QueryTask,
    QueryExecutionRecord,
    EvidenceItem,
    HypothesisStatus,
    Hypothesis,
    ValidationIssueType,
    ValidationSeverity,
    ValidationIssueStatus,
    ValidationIssue,
    InvestigationPlan,
    InvestigationState,
    validate_investigation_plan,
)
from app.services.analysis.investigation_engine import InvestigationEngine
from app.services.analysis.evidence_manager import (
    EvidenceManager,
    InvestigationProgressEvaluator,
    InvestigationProgress,
)
from app.services.analysis.query_selector import (
    QuerySelector,
    QuerySelectorConfig,
    QuerySelectionResult,
    CandidateEvaluation,
)
from app.services.analysis.hypothesis_manager import (
    HypothesisManager,
    SegmentContribution,
)
from app.services.analysis.cross_query_validator import (
    CrossQueryValidator,
    ValidationReport,
    GroundingReadiness,
)
from app.services.analysis.grounded_report_composer import (
    GroundedAnalysisContext,
    GroundedReportComposer,
)
from app.services.analysis.production_optimizer import (
    ModelRouter,
    ModelTier,
    ModelRouteDecision,
    QueryDeduplicator,
    InvestigationCache,
    SemanticQueryCache,
    SelfConsistencyGate,
    SystemMetricsTracker,
    TelemetrySnapshot,
    investigation_cache,
    semantic_query_cache,
)


