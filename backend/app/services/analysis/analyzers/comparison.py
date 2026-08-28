"""Comparison Analyzer: compares metrics across cohorts, categories, or time periods."""
from typing import Any, Dict, List, Tuple

from app.services.analysis.analyzers.base import BaseAnalysisAnalyzer
from app.services.analysis.models import (
    AnalysisTask,
    AnalysisTaskResult,
    ComputationType,
    DataRetrievalRequirement,
)
from app.agent.semantic.models import AnalysisOperation, QuerySpec


class ComparisonAnalyzer(BaseAnalysisAnalyzer):
    operation = AnalysisOperation.COMPARE
    name = "Cohort & Period Comparison"

    def plan_tasks(
        self, spec: QuerySpec
    ) -> Tuple[List[AnalysisTask], List[DataRetrievalRequirement], List[str]]:
        req = DataRetrievalRequirement(
            requirement_id="req_comparison_groups",
            description="Retrieve metrics grouped by compared categories or time windows",
            sub_question=f"Compare metrics for {spec.raw_question}",
            metrics=spec.metrics,
            dimensions=spec.dimensions,
            time_expressions=spec.time_expressions,
        )
        task = AnalysisTask(
            task_id="task_calc_comparison_variance",
            name="Calculate Absolute & Percentage Variance",
            operation=AnalysisOperation.COMPARE,
            description="Compute absolute difference and percentage variance between groups",
            computation_type=ComputationType.GROWTH_RATE,
            data_requirement_ids=["req_comparison_groups"],
        )
        return [task], [req], ["Variance and percentage difference between groups"]

    def execute(
        self,
        task: AnalysisTask,
        rows: List[Dict[str, Any]],
        numeric_cols: List[str],
        dimension_cols: List[str],
    ) -> AnalysisTaskResult:
        from app.services.analysis.engines.aggregation_comparison import AggregationComparisonEngine

        findings = []
        metrics: Dict[str, Any] = {}

        if numeric_cols and len(rows) >= 2:
            val_col = numeric_cols[0]
            dim_col = dimension_cols[0] if dimension_cols else "group"
            comp_res = AggregationComparisonEngine.compute_comparison(rows, group_col=dim_col, metric_col=val_col)
            metrics = {
                "total_sum": comp_res.get("total_sum", 0.0),
                "highest_group": comp_res.get("highest_group"),
                "lowest_group": comp_res.get("lowest_group"),
            }
            for c in comp_res.get("comparisons", []):
                metrics[f"diff_{c['to_group']}_vs_{c['from_group']}"] = c["difference"]
                metrics[f"pct_{c['to_group']}_vs_{c['from_group']}"] = c["growth_pct"]
            findings = AggregationComparisonEngine.generate_findings(comp_res)

        return AnalysisTaskResult(
            task_id=task.task_id,
            name=task.name,
            computed_metrics=metrics,
            findings=findings,
        )
