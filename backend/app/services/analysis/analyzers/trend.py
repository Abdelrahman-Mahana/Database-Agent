"""Trend Analyzer: calculates trajectories, growth rates, momentum, and peaks/troughs."""
from typing import Any, Dict, List, Tuple

from app.services.analysis.analyzers.base import BaseAnalysisAnalyzer
from app.services.analysis.models import (
    AnalysisTask,
    AnalysisTaskResult,
    ComputationType,
    DataRetrievalRequirement,
)
from app.agent.semantic.models import AnalysisOperation, QuerySpec


class TrendAnalyzer(BaseAnalysisAnalyzer):
    operation = AnalysisOperation.TREND
    name = "Trend & Growth Analysis"

    def plan_tasks(
        self, spec: QuerySpec
    ) -> Tuple[List[AnalysisTask], List[DataRetrievalRequirement], List[str]]:
        req = DataRetrievalRequirement(
            requirement_id="req_trend_time_series",
            analytical_task_id="task_calc_growth_rate",
            description="Retrieve ordered time-series values across periods",
            sub_question=f"What is the time series trend for {spec.raw_question}?",
            expected_evidence="Time-series trajectory and period-over-period growth rates",
            metrics=spec.metrics,
            dimensions=spec.dimensions,
            time_expressions=spec.time_expressions,
        )
        task_1 = AnalysisTask(
            task_id="task_calc_growth_rate",
            name="Calculate Trajectory & Growth Rate",
            operation=AnalysisOperation.TREND,
            description="Calculate period-over-period growth rates and overall velocity",
            computation_type=ComputationType.GROWTH_RATE,
            data_requirement_ids=["req_trend_time_series"],
        )
        task_2 = AnalysisTask(
            task_id="task_peak_trough_extrema",
            name="Identify Peak and Trough Periods",
            operation=AnalysisOperation.COMPARE,
            description="Identify highest peak and lowest trough intervals in the series",
            computation_type=ComputationType.PEAK_AND_TROUGH,
            data_requirement_ids=["req_trend_time_series"],
            dependencies=["task_calc_growth_rate"],
        )
        return [task_1, task_2], [req], ["Overall growth trajectory", "Peak and trough intervals"]

    def execute(
        self,
        task: AnalysisTask,
        rows: List[Dict[str, Any]],
        numeric_cols: List[str],
        dimension_cols: List[str],
    ) -> AnalysisTaskResult:
        from app.services.analysis.engines.trend import TrendEngine

        findings = []
        metrics: Dict[str, Any] = {}

        if numeric_cols and len(rows) > 1:
            val_col = numeric_cols[0]
            dim_col = dimension_cols[0] if dimension_cols else "period"
            trend_res = TrendEngine.compute_trend(rows, date_col=dim_col, metric_col=val_col)
            
            metrics["granularity"] = trend_res.get("granularity")
            metrics["overall_growth_pct"] = trend_res.get("overall_growth_pct", 0.0)
            metrics["trend_direction"] = trend_res.get("trend_direction")
            metrics["linear_slope"] = trend_res.get("linear_slope")
            if trend_res.get("peak"):
                metrics["peak_period"] = trend_res["peak"]["period"]
                metrics["peak_value"] = trend_res["peak"]["value"]
            if trend_res.get("trough"):
                metrics["trough_period"] = trend_res["trough"]["period"]
                metrics["trough_value"] = trend_res["trough"]["value"]

            findings = TrendEngine.generate_findings(trend_res)

        return AnalysisTaskResult(
            task_id=task.task_id,
            name=task.name,
            computed_metrics=metrics,
            findings=findings,
        )
