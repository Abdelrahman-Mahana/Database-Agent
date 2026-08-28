"""Exploratory Analyzer: comprehensive deep-dive combining totals, growth, peaks, and anomalies."""
from typing import Any, Dict, List, Tuple

from app.services.analysis.analyzers.base import BaseAnalysisAnalyzer
from app.services.analysis.models import (
    AnalysisTask,
    AnalysisTaskResult,
    ComputationType,
    DataRetrievalRequirement,
)
from app.agent.semantic.models import AnalysisOperation, QuerySpec


class ExploratoryAnalyzer(BaseAnalysisAnalyzer):
    operation = AnalysisOperation.SEGMENT
    name = "Exploratory Deep Dive"

    def plan_tasks(
        self, spec: QuerySpec
    ) -> Tuple[List[AnalysisTask], List[DataRetrievalRequirement], List[str]]:
        req_1 = DataRetrievalRequirement(
            requirement_id="req_total_metrics",
            description="Retrieve overall total volume and core aggregated metrics",
            sub_question=f"What is the overall total and key metrics for {spec.raw_question}?",
            metrics=spec.metrics,
            dimensions=[],
            aggregations=["SUM", "COUNT", "AVG"],
        )
        req_2 = DataRetrievalRequirement(
            requirement_id="req_periodic_breakdown",
            description="Retrieve periodic breakdown across time dimensions",
            sub_question=f"What is the periodic breakdown and distribution for {spec.raw_question}?",
            metrics=spec.metrics,
            dimensions=spec.dimensions or ["date"],
            aggregations=["SUM", "COUNT"],
        )
        task_1 = AnalysisTask(
            task_id="task_total_overview",
            name="Calculate Total Overview",
            operation=AnalysisOperation.AGGREGATE,
            description="Calculate baseline aggregates, overall volume, and count of records",
            computation_type=ComputationType.TOTAL,
            data_requirement_ids=["req_total_metrics"],
        )
        task_2 = AnalysisTask(
            task_id="task_periodic_trend",
            name="Calculate Periodic Distribution & Growth",
            operation=AnalysisOperation.TREND,
            description="Calculate periodic sales trajectory and growth rate across intervals",
            computation_type=ComputationType.GROWTH_RATE,
            data_requirement_ids=["req_periodic_breakdown"],
            dependencies=["task_total_overview"],
        )
        task_3 = AnalysisTask(
            task_id="task_peak_trough",
            name="Identify Peaks and Troughs",
            operation=AnalysisOperation.COMPARE,
            description="Identify highest and lowest performance intervals",
            computation_type=ComputationType.PEAK_AND_TROUGH,
            data_requirement_ids=["req_periodic_breakdown"],
            dependencies=["task_periodic_trend"],
        )
        task_4 = AnalysisTask(
            task_id="task_anomaly_detection",
            name="Detect Unusual Fluctuations & Outliers",
            operation=AnalysisOperation.ANOMALY,
            description="Detect statistically significant dips, drops, or outlier periods",
            computation_type=ComputationType.OUTLIER_DETECTION,
            data_requirement_ids=["req_periodic_breakdown"],
            dependencies=["task_periodic_trend"],
        )
        return (
            [task_1, task_2, task_3, task_4],
            [req_1, req_2],
            ["Total volume baseline", "Growth rate trajectory", "Peak and trough intervals", "Outlier occurrences"],
        )

    def execute(
        self,
        task: AnalysisTask,
        rows: List[Dict[str, Any]],
        numeric_cols: List[str],
        dimension_cols: List[str],
    ) -> AnalysisTaskResult:
        # Exploratory delegates execution of sub-tasks to individual analyzers (or basic summary)
        from app.services.analysis.analyzers.aggregation import AggregationAnalyzer
        from app.services.analysis.analyzers.trend import TrendAnalyzer
        from app.services.analysis.analyzers.anomaly import AnomalyAnalyzer

        if task.computation_type == ComputationType.TOTAL:
            return AggregationAnalyzer().execute(task, rows, numeric_cols, dimension_cols)
        elif task.computation_type in (ComputationType.GROWTH_RATE, ComputationType.PEAK_AND_TROUGH):
            return TrendAnalyzer().execute(task, rows, numeric_cols, dimension_cols)
        elif task.computation_type == ComputationType.OUTLIER_DETECTION:
            return AnomalyAnalyzer().execute(task, rows, numeric_cols, dimension_cols)

        return AnalysisTaskResult(
            task_id=task.task_id,
            name=task.name,
            computed_metrics={"rows": len(rows)},
            findings=[f"Exploratory step {task.name} completed."],
        )
