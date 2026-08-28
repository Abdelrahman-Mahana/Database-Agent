"""Aggregation Analyzer: calculates totals, averages, counts, and baseline metrics."""
from typing import Any, Dict, List, Tuple

from app.services.analysis.analyzers.base import BaseAnalysisAnalyzer
from app.services.analysis.models import (
    AnalysisTask,
    AnalysisTaskResult,
    ComputationType,
    DataRetrievalRequirement,
)
from app.agent.semantic.models import AnalysisOperation, QuerySpec


class AggregationAnalyzer(BaseAnalysisAnalyzer):
    operation = AnalysisOperation.AGGREGATE
    name = "Aggregation & Totals"

    def plan_tasks(
        self, spec: QuerySpec
    ) -> Tuple[List[AnalysisTask], List[DataRetrievalRequirement], List[str]]:
        req = DataRetrievalRequirement(
            requirement_id="req_aggregate_metrics",
            description="Retrieve aggregated metrics and counts",
            sub_question=spec.raw_question,
            metrics=spec.metrics,
            dimensions=spec.dimensions,
            aggregations=spec.aggregations or ["COUNT", "SUM", "AVG"],
            limit=spec.limit,
        )
        task = AnalysisTask(
            task_id="task_calc_totals",
            name="Calculate Aggregates & Volume",
            operation=AnalysisOperation.AGGREGATE,
            description="Calculate total sums, averages, and row counts",
            computation_type=ComputationType.TOTAL,
            data_requirement_ids=["req_aggregate_metrics"],
        )
        return [task], [req], ["Overall total volume and metric summaries"]

    def execute(
        self,
        task: AnalysisTask,
        rows: List[Dict[str, Any]],
        numeric_cols: List[str],
        dimension_cols: List[str],
    ) -> AnalysisTaskResult:
        from app.services.analysis.engines.aggregation_comparison import AggregationComparisonEngine

        agg_res = AggregationComparisonEngine.compute_aggregations(rows, numeric_cols=numeric_cols)
        metrics: Dict[str, Any] = {"total_rows": agg_res.get("row_count", len(rows))}
        findings = [f"Total record count: {agg_res.get('row_count', len(rows))}"]

        for col, stats in agg_res.get("columns", {}).items():
            metrics[f"sum_{col}"] = stats["sum"]
            metrics[f"avg_{col}"] = stats["average"]
            metrics[f"min_{col}"] = stats["min"]
            metrics[f"max_{col}"] = stats["max"]
            findings.append(f"Total {col}: {stats['sum']:,.2f} (Average: {stats['average']:,.2f}, Min: {stats['min']:,.2f}, Max: {stats['max']:,.2f})")

        return AnalysisTaskResult(
            task_id=task.task_id,
            name=task.name,
            computed_metrics=metrics,
            findings=findings,
        )
