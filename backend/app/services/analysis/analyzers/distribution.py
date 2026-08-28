"""Distribution Analyzer: calculates frequency distribution, category proportions, and spread."""
from typing import Any, Dict, List, Tuple

from app.services.analysis.analyzers.base import BaseAnalysisAnalyzer
from app.services.analysis.models import (
    AnalysisTask,
    AnalysisTaskResult,
    ComputationType,
    DataRetrievalRequirement,
)
from app.agent.semantic.models import AnalysisOperation, QuerySpec


class DistributionAnalyzer(BaseAnalysisAnalyzer):
    operation = AnalysisOperation.DISTRIBUTION
    name = "Distribution & Categorical Breakdown"

    def plan_tasks(
        self, spec: QuerySpec
    ) -> Tuple[List[AnalysisTask], List[DataRetrievalRequirement], List[str]]:
        req = DataRetrievalRequirement(
            requirement_id="req_distribution_breakdown",
            description="Retrieve counts and sums grouped by categorical dimension",
            sub_question=f"Show distribution and breakdown for {spec.raw_question}",
            metrics=spec.metrics,
            dimensions=spec.dimensions,
        )
        task = AnalysisTask(
            task_id="task_calc_distribution_spread",
            name="Calculate Distribution & Category Shares",
            operation=AnalysisOperation.DISTRIBUTION,
            description="Calculate percentage distribution, top category concentration, and spread",
            computation_type=ComputationType.DISTRIBUTION_SPREAD,
            data_requirement_ids=["req_distribution_breakdown"],
        )
        return [task], [req], ["Category percentage distribution and top concentration shares"]

    def execute(
        self,
        task: AnalysisTask,
        rows: List[Dict[str, Any]],
        numeric_cols: List[str],
        dimension_cols: List[str],
    ) -> AnalysisTaskResult:
        from app.services.analysis.engines.distribution import DistributionEngine

        findings = []
        metrics: Dict[str, Any] = {}

        if numeric_cols:
            val_col = numeric_cols[0]
            dist_res = DistributionEngine.compute_numeric_distribution(rows, numeric_col=val_col)
            metrics = {
                "count": dist_res.get("count", len(rows)),
                "mean": dist_res.get("mean"),
                "median": dist_res.get("median"),
                "percentiles": dist_res.get("percentiles"),
                "buckets": dist_res.get("buckets"),
            }
            findings = DistributionEngine.generate_findings(dist_res)
        elif dimension_cols:
            dim_col = dimension_cols[0]
            cat_res = DistributionEngine.compute_categorical_frequency(rows, categorical_col=dim_col)
            metrics = {
                "total_count": cat_res.get("total_count", len(rows)),
                "unique_categories": cat_res.get("unique_categories"),
                "categories": cat_res.get("categories"),
            }
            findings = DistributionEngine.generate_findings(cat_res)

        return AnalysisTaskResult(
            task_id=task.task_id,
            name=task.name,
            computed_metrics=metrics,
            findings=findings,
        )
