"""Forecasting Analyzer: computes linear trend slope and projects future period values."""
from typing import Any, Dict, List, Tuple

from app.services.analysis.analyzers.base import BaseAnalysisAnalyzer
from app.services.analysis.models import (
    AnalysisTask,
    AnalysisTaskResult,
    ComputationType,
    DataRetrievalRequirement,
)
from app.agent.semantic.models import AnalysisOperation, QuerySpec


class ForecastingAnalyzer(BaseAnalysisAnalyzer):
    operation = AnalysisOperation.FORECAST
    name = "Forecasting & Predictive Projection"

    def plan_tasks(
        self, spec: QuerySpec
    ) -> Tuple[List[AnalysisTask], List[DataRetrievalRequirement], List[str]]:
        req = DataRetrievalRequirement(
            requirement_id="req_historical_baseline",
            description="Retrieve historical time series baseline data",
            sub_question=f"Retrieve historical time series data for {spec.raw_question}",
            metrics=spec.metrics,
            dimensions=spec.dimensions,
        )
        task = AnalysisTask(
            task_id="task_calc_linear_forecast",
            name="Forecast Next Period Values & Prediction Bounds",
            operation=AnalysisOperation.FORECAST,
            description="Compute Linear Trend OLS, Moving Average, and 95% Confidence Intervals",
            computation_type=ComputationType.FORECAST_TREND,
            data_requirement_ids=["req_historical_baseline"],
        )
        return [task], [req], [
            "Projected next period values",
            "Linear trend trajectory and regression slope",
            "95% Confidence Interval prediction bounds",
            "Moving average and baseline comparisons",
        ]

    def execute(
        self,
        task: AnalysisTask,
        rows: List[Dict[str, Any]],
        numeric_cols: List[str],
        dimension_cols: List[str],
    ) -> AnalysisTaskResult:
        from app.services.analysis.engines.forecasting import ForecastingEngine

        findings = []
        metrics: Dict[str, Any] = {}

        if numeric_cols and len(rows) >= 2:
            val_col = numeric_cols[0]
            date_col = dimension_cols[0] if dimension_cols else None
            forecast_res = ForecastingEngine.forecast_all(
                rows=rows,
                metric_col=val_col,
                date_col=date_col,
                periods_ahead=3,
            )

            metrics = {
                "last_observed_value": forecast_res.get("last_observed_value"),
                "recommended_next_period_value": forecast_res.get("recommended_next_period_value"),
                "linear_slope": forecast_res.get("linear_trend_model", {}).get("slope"),
                "trend_direction": forecast_res.get("linear_trend_model", {}).get("trend_direction"),
                "r_squared": forecast_res.get("linear_trend_model", {}).get("r_squared"),
                "projections": forecast_res.get("linear_trend_model", {}).get("projections"),
            }
            findings = ForecastingEngine.generate_findings(forecast_res)

        return AnalysisTaskResult(
            task_id=task.task_id,
            name=task.name,
            computed_metrics=metrics,
            findings=findings,
        )
