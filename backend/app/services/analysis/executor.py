"""Analysis Executor: executes analytical tasks by delegating to registered Analyzers."""
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.services.analysis.models import (
    AnalysisExecutionResult,
    AnalysisPlan,
    AnalysisTask,
    AnalysisTaskResult,
)
from app.services.analysis.registry import ANALYSIS_REGISTRY, AnalysisStrategyRegistry

logger = logging.getLogger(__name__)


class AnalysisExecutor:
    """Executes the analytical calculations specified in an AnalysisPlan on retrieved SQL rows.

    Uses ANALYSIS_REGISTRY to dynamically dispatch execution to dedicated analyzers without if/else logic.
    """

    def execute(
        self,
        plan: AnalysisPlan,
        rows: List[Dict[str, Any]],
        prior_results: Optional[List[Dict[str, Any]]] = None,
    ) -> AnalysisExecutionResult:
        """Run all tasks in the plan across the dataset and generate verified findings."""
        if not rows:
            return AnalysisExecutionResult(
                plan=plan,
                task_results=[],
                all_findings=["No data records were returned for analytical processing."],
                computed_summary={},
                raw_data=[],
                success=True,
            )

        task_results: List[AnalysisTaskResult] = []
        all_findings: List[str] = []
        summary_metrics: Dict[str, Any] = {}

        # Extract numeric columns and dates/dimensions
        numeric_cols, dimension_cols = self._inspect_columns(rows)

        for task in plan.tasks:
            try:
                # Dispatch execution to the registered analyzer
                analyzer_cls = AnalysisStrategyRegistry.get(task.operation)
                analyzer = analyzer_cls()
                task_res = analyzer.execute(task, rows, numeric_cols, dimension_cols)
            except Exception as e:
                logger.warning("Task execution failed for '%s': %s", task.name, e)
                task_res = AnalysisTaskResult(
                    task_id=task.task_id,
                    name=task.name,
                    status="failed",
                    error=str(e),
                )

            task_results.append(task_res)
            if task_res.findings:
                all_findings.extend(task_res.findings)
            if task_res.computed_metrics:
                summary_metrics.update(task_res.computed_metrics)

        return AnalysisExecutionResult(
            plan=plan,
            task_results=task_results,
            all_findings=all_findings,
            computed_summary=summary_metrics,
            raw_data=rows[:100],
            success=True,
        )

    def _inspect_columns(self, rows: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
        """Inspect and categorize columns as numeric or dimensional."""
        if not rows:
            return [], []
        first_row = rows[0]
        numeric_cols = []
        dimension_cols = []
        for k, v in first_row.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                numeric_cols.append(k)
            else:
                try:
                    float(v)
                    numeric_cols.append(k)
                except (ValueError, TypeError):
                    dimension_cols.append(k)
        return numeric_cols, dimension_cols
