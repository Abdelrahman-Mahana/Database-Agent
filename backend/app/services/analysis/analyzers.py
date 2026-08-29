from __future__ import annotations
from abc import ABC, abstractmethod
from app.agent.semantic.models import AnalysisOperation, QuerySpec
from app.services.analysis.models import (
    AnalysisTask,
    AnalysisTaskResult,
    ComputationType,
    DataRetrievalRequirement,
)
from typing import Any, Dict, List, Optional, Tuple
from typing import Any, Dict, List, Tuple
import math


# --- From base.py ---
class BaseAnalysisAnalyzer(ABC):
    """Abstract Base Class for all analytical domain analyzers.

    Each analyzer defines how to:
    1. Plan analytical tasks and data retrieval requirements for its operation (`plan_tasks`).
    2. Compute metrics, detect anomalies/trends, and generate verified findings (`execute`).
    """

    operation: AnalysisOperation
    name: str

    @abstractmethod
    def plan_tasks(
        self, spec: QuerySpec
    ) -> Tuple[List[AnalysisTask], List[DataRetrievalRequirement], List[str]]:
        """Generate tasks, data retrieval requirements, and expected insights for this operation."""
        pass

    @abstractmethod
    def execute(
        self,
        task: AnalysisTask,
        rows: List[Dict[str, Any]],
        numeric_cols: List[str],
        dimension_cols: List[str],
    ) -> AnalysisTaskResult:
        """Execute the analytical computation on retrieved SQL data."""
        pass







# --- From aggregation.py ---
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
        from app.services.analysis.engines import AggregationComparisonEngine

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



# --- From anomaly.py ---
class AnomalyAnalyzer(BaseAnalysisAnalyzer):
    operation = AnalysisOperation.ANOMALY
    name = "Anomaly & Outlier Detection"

    def plan_tasks(
        self, spec: QuerySpec
    ) -> Tuple[List[AnalysisTask], List[DataRetrievalRequirement], List[str]]:
        req = DataRetrievalRequirement(
            requirement_id="req_distribution_records",
            description="Retrieve numeric data distribution records to identify outliers",
            sub_question=f"Fetch numeric data distribution for {spec.raw_question}",
            metrics=spec.metrics,
            dimensions=spec.dimensions,
        )
        task = AnalysisTask(
            task_id="task_detect_zscore_outliers",
            name="Detect Statistical Outliers",
            operation=AnalysisOperation.ANOMALY,
            description="Calculate mean, standard deviation, and detect values beyond ±2 standard deviations",
            computation_type=ComputationType.OUTLIER_DETECTION,
            data_requirement_ids=["req_distribution_records"],
        )
        return [task], [req], ["Statistical outliers, unusual spikes, and anomalous dips"]

    def execute(
        self,
        task: AnalysisTask,
        rows: List[Dict[str, Any]],
        numeric_cols: List[str],
        dimension_cols: List[str],
    ) -> AnalysisTaskResult:
        from app.services.analysis.engines import AnomalyDetectionEngine

        findings = []
        anomalies = []
        metrics: Dict[str, Any] = {}

        if numeric_cols and len(rows) >= 2:
            val_col = numeric_cols[0]
            dim_col = dimension_cols[0] if dimension_cols else None
            anom_res = AnomalyDetectionEngine.detect_all(rows, metric_col=val_col, label_col=dim_col)
            
            anomalies = anom_res.get("anomalies", [])
            metrics = {
                "total_records": anom_res.get("total_records", len(rows)),
                "anomalies_count": len(anomalies),
                "iqr_summary": anom_res.get("iqr_summary"),
                "zscore_summary": anom_res.get("zscore_summary"),
                "percentage_summary": anom_res.get("percentage_summary"),
            }
            findings = AnomalyDetectionEngine.generate_findings(anom_res)

        return AnalysisTaskResult(
            task_id=task.task_id,
            name=task.name,
            computed_metrics=metrics,
            findings=findings,
            anomalies=anomalies,
        )



# --- From comparison.py ---
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
        from app.services.analysis.engines import AggregationComparisonEngine

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


# --- From correlation.py ---
class CorrelationAnalyzer(BaseAnalysisAnalyzer):
    operation = AnalysisOperation.CORRELATION
    name = "Correlation & Association Analysis"

    def plan_tasks(
        self, spec: QuerySpec
    ) -> Tuple[List[AnalysisTask], List[DataRetrievalRequirement], List[str]]:
        req = DataRetrievalRequirement(
            requirement_id="req_paired_variables",
            description="Retrieve paired numerical variables to evaluate statistical correlation",
            sub_question=f"Retrieve paired numeric variables for {spec.raw_question}",
            metrics=spec.metrics,
        )
        task = AnalysisTask(
            task_id="task_calc_pearson_correlation",
            name="Calculate Correlation, Direction, Strength, and Limitations",
            operation=AnalysisOperation.CORRELATION,
            description="Calculate Pearson r, coefficient of determination R², determine direction and strength, and formulate limitations",
            computation_type=ComputationType.CORRELATION,
            data_requirement_ids=["req_paired_variables"],
        )
        return [task], [req], [
            "Pearson correlation coefficient (r)",
            "Relationship direction (positive/negative)",
            "Relationship strength (strong/moderate/weak)",
            "Methodological limitations and causality disclaimers",
        ]

    def execute(
        self,
        task: AnalysisTask,
        rows: List[Dict[str, Any]],
        numeric_cols: List[str],
        dimension_cols: List[str],
    ) -> AnalysisTaskResult:
        from app.services.analysis.engines import CorrelationEngine

        findings = []
        metrics: Dict[str, Any] = {}

        col_x = numeric_cols[0] if len(numeric_cols) >= 1 else None
        col_y = numeric_cols[1] if len(numeric_cols) >= 2 else None

        corr_res = CorrelationEngine.compute_correlation(rows, col_x=col_x, col_y=col_y)
        metrics = {
            "col_x": corr_res.get("col_x"),
            "col_y": corr_res.get("col_y"),
            "sample_size": corr_res.get("sample_size", 0),
            "pearson_r": corr_res.get("pearson_r", 0.0),
            "r_squared": corr_res.get("r_squared", 0.0),
            "variance_explained_pct": corr_res.get("variance_explained_pct", 0.0),
            "direction": corr_res.get("direction"),
            "strength": corr_res.get("strength"),
            "limitations": corr_res.get("limitations", []),
        }
        findings = CorrelationEngine.generate_findings(corr_res)

        return AnalysisTaskResult(
            task_id=task.task_id,
            name=task.name,
            computed_metrics=metrics,
            findings=findings,
        )


# --- From data_quality.py ---
class DataQualityAnalyzer(BaseAnalysisAnalyzer):
    operation = AnalysisOperation.DATA_QUALITY
    name = "Data Quality & Integrity Audit"

    def plan_tasks(
        self, spec: QuerySpec
    ) -> Tuple[List[AnalysisTask], List[DataRetrievalRequirement], List[str]]:
        req = DataRetrievalRequirement(
            requirement_id="req_audit_records",
            description="Retrieve table records to audit completeness, duplicates, invalid ranges, and casing consistency",
            sub_question=f"Retrieve records to audit data quality for {spec.raw_question}",
            metrics=spec.metrics,
            dimensions=spec.dimensions,
        )
        task = AnalysisTask(
            task_id="task_audit_data_quality",
            name="Audit 7-Dimension Data Quality & Integrity",
            operation=AnalysisOperation.DATA_QUALITY,
            description="Inspect records for missing values, duplicates, outliers, invalid ranges, high cardinality, low variance, and inconsistent categories",
            computation_type=ComputationType.DATA_QUALITY_AUDIT,
            data_requirement_ids=["req_audit_records"],
        )
        return [task], [req], [
            "Overall Data Quality Score (0-100%)",
            "Missing values count and column completeness",
            "Duplicate records count and percentage",
            "Invalid ranges and logical violations",
            "High cardinality and low variance warnings",
            "Inconsistent category casings and whitespace variations",
        ]

    def execute(
        self,
        task: AnalysisTask,
        rows: List[Dict[str, Any]],
        numeric_cols: List[str],
        dimension_cols: List[str],
    ) -> AnalysisTaskResult:
        from app.services.analysis.engines import DataQualityEngine

        findings = []
        metrics: Dict[str, Any] = {}

        if rows:
            audit = DataQualityEngine.audit_dataset(rows)
            metrics = {
                "overall_quality_score": audit.get("overall_quality_score", 100.0),
                "total_rows": audit.get("total_rows", len(rows)),
                "completeness_pct": audit.get("missing_summary", {}).get("overall_completeness_pct", 100.0),
                "duplicate_count": audit.get("duplicate_summary", {}).get("duplicate_count", 0),
                "invalid_ranges_count": audit.get("invalid_ranges_summary", {}).get("total_violations", 0),
                "high_cardinality_cols": len(audit.get("high_cardinality_summary", {}).get("high_cardinality_columns", [])),
                "low_variance_cols": len(audit.get("low_variance_summary", {}).get("low_variance_columns", [])),
                "casing_inconsistencies": len(audit.get("inconsistency_summary", {}).get("inconsistencies", [])),
            }
            findings = DataQualityEngine.generate_findings(audit)

        return AnalysisTaskResult(
            task_id=task.task_id,
            name=task.name,
            computed_metrics=metrics,
            findings=findings,
        )


# --- From distribution.py ---
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
        from app.services.analysis.engines import DistributionEngine

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


# --- From exploratory.py ---
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
        from app.services.analysis.analyzers import AggregationAnalyzer
        from app.services.analysis.analyzers import TrendAnalyzer
        from app.services.analysis.analyzers import AnomalyAnalyzer

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


# --- From forecasting.py ---
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
        from app.services.analysis.engines import ForecastingEngine

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


# --- From root_cause.py ---
class RootCauseAnalyzer(BaseAnalysisAnalyzer):
    operation = AnalysisOperation.ROOT_CAUSE
    name = "Root Cause & Driver Investigation"

    def plan_tasks(
        self, spec: QuerySpec
    ) -> Tuple[List[AnalysisTask], List[DataRetrievalRequirement], List[str]]:
        req_1 = DataRetrievalRequirement(
            requirement_id="req_overall_drop_period",
            analytical_task_id="task_isolate_drop_period",
            description="Retrieve primary metric trajectory across time to quantify total decline",
            sub_question=f"What is the overall timeline and magnitude of change for {spec.raw_question}?",
            expected_evidence="Baseline timeline and magnitude of total decline",
            metrics=spec.metrics,
            dimensions=spec.dimensions,
        )
        req_2 = DataRetrievalRequirement(
            requirement_id="req_driver_breakdown",
            analytical_task_id="task_identify_driver_segments",
            description="Retrieve multi-dimensional metric breakdown across categories, products, or locations during drop period",
            sub_question=f"Which categories or dimensions contributed most to the decline in {spec.raw_question}?",
            expected_evidence="Category and regional contribution to total decline",
            metrics=spec.metrics,
            dimensions=spec.dimensions or ["category", "product", "region"],
        )
        task_1 = AnalysisTask(
            task_id="task_isolate_drop_period",
            name="Quantify Overall Decline and Affected Time Period",
            operation=AnalysisOperation.TREND,
            description="Determine exact baseline vs current value and total magnitude of metric drop",
            computation_type=ComputationType.GROWTH_RATE,
            data_requirement_ids=["req_overall_drop_period"],
        )
        task_2 = AnalysisTask(
            task_id="task_identify_driver_segments",
            name="Decompose Dimensions and Rank Negative Contributors",
            operation=AnalysisOperation.ROOT_CAUSE,
            description="Decompose metrics across dimensions, isolate negative changes, rank contributors, and generate mathematical proof",
            computation_type=ComputationType.SEGMENT_RANKING,
            data_requirement_ids=["req_driver_breakdown"],
            dependencies=["task_isolate_drop_period"],
        )
        return (
            [task_1, task_2],
            [req_1, req_2],
            [
                "Overall decline percentage and volume",
                "Affected time window",
                "Ranked negative dimensional contributors",
                "Contribution percentage share of each driver",
                "Grounded evidence facts for LLM explanation without hallucination",
            ],
        )

    def execute(
        self,
        task: AnalysisTask,
        rows: List[Dict[str, Any]],
        numeric_cols: List[str],
        dimension_cols: List[str],
    ) -> AnalysisTaskResult:
        from app.services.analysis.engines import RootCauseEngine

        findings = []
        metrics: Dict[str, Any] = {}

        if numeric_cols and rows:
            val_col = numeric_cols[0]
            # Identify time column if present in dimension_cols
            time_col = next((c for c in dimension_cols if any(t in c.lower() for t in ("date", "month", "year", "time", "period"))), None)
            feature_dims = [c for c in dimension_cols if c != time_col]
            if not feature_dims and dimension_cols:
                feature_dims = [dimension_cols[0]]

            investigation = RootCauseEngine.run_investigation(
                rows=rows,
                metric_col=val_col,
                dimension_cols=feature_dims,
                time_col=time_col,
            )

            # Hypothesis-driven evaluation (Phase 6)
            from app.services.analysis.hypothesis_manager import HypothesisManager
            contributions = []
            if feature_dims:
                contributions = HypothesisManager.calculate_segment_contributions(
                    rows=rows,
                    dimension_col=feature_dims[0],
                    metric_col=val_col,
                    time_col=time_col,
                )

            metrics = {
                "overall": investigation.get("overall"),
                "dimensions_investigated": investigation.get("dimensions_investigated"),
                "segment_contributions": [c.__dict__ for c in contributions] if contributions else [],
            }
            findings = RootCauseEngine.generate_findings(investigation)

        return AnalysisTaskResult(
            task_id=task.task_id,
            name=task.name,
            computed_metrics=metrics,
            findings=findings,
        )


# --- From segmentation.py ---
class SegmentationAnalyzer(BaseAnalysisAnalyzer):
    operation = AnalysisOperation.SEGMENT
    name = "Entity Segmentation & Clustering"

    def plan_tasks(
        self, spec: QuerySpec
    ) -> Tuple[List[AnalysisTask], List[DataRetrievalRequirement], List[str]]:
        req = DataRetrievalRequirement(
            requirement_id="req_segment_metrics",
            description="Retrieve multi-metric behavioral data grouped by entity",
            sub_question=f"Segment entities and calculate totals for {spec.raw_question}",
            metrics=spec.metrics,
            dimensions=spec.dimensions,
        )
        task = AnalysisTask(
            task_id="task_calc_segments",
            name="Segment and Rank Entity Cohorts",
            operation=AnalysisOperation.SEGMENT,
            description="Group entities into high, medium, and low value segments based on performance metrics",
            computation_type=ComputationType.SEGMENT_RANKING,
            data_requirement_ids=["req_segment_metrics"],
        )
        return [task], [req], ["Entity segmentation breakdown (High/Medium/Low cohorts)"]

    def execute(
        self,
        task: AnalysisTask,
        rows: List[Dict[str, Any]],
        numeric_cols: List[str],
        dimension_cols: List[str],
    ) -> AnalysisTaskResult:
        findings = []
        metrics: Dict[str, Any] = {}

        if numeric_cols and rows:
            val_col = numeric_cols[0]
            dim_col = dimension_cols[0] if dimension_cols else "entity"
            
            entities = []
            for r in rows:
                try:
                    entities.append((str(r.get(dim_col, "")), float(r.get(val_col, 0))))
                except (ValueError, TypeError):
                    pass

            if entities:
                sorted_entities = sorted(entities, key=lambda x: x[1], reverse=True)
                n = len(sorted_entities)
                top_tier = sorted_entities[: max(1, n // 5)]
                bottom_tier = sorted_entities[-max(1, n // 5):]
                
                metrics["top_tier_count"] = len(top_tier)
                metrics["bottom_tier_count"] = len(bottom_tier)
                findings.append(f"Segmented {n} entities: Top 20% tier averages {sum(v for _, v in top_tier)/len(top_tier):,.2f}, bottom 20% tier averages {sum(v for _, v in bottom_tier)/len(bottom_tier):,.2f}.")

        return AnalysisTaskResult(
            task_id=task.task_id,
            name=task.name,
            computed_metrics=metrics,
            findings=findings,
        )


# --- From statistical_test.py ---
class StatisticalTestAnalyzer(BaseAnalysisAnalyzer):
    operation = AnalysisOperation.STATISTICAL_TEST
    name = "Statistical Hypothesis Testing"

    def plan_tasks(
        self, spec: QuerySpec
    ) -> Tuple[List[AnalysisTask], List[DataRetrievalRequirement], List[str]]:
        req = DataRetrievalRequirement(
            requirement_id="req_sample_data",
            description="Retrieve numeric samples and grouping dimensions for statistical validation",
            sub_question=f"Fetch data samples for {spec.raw_question}",
            metrics=spec.metrics,
            dimensions=spec.dimensions,
        )
        task = AnalysisTask(
            task_id="task_calc_statistical_metrics",
            name="Perform Statistical Significance & Hypothesis Testing",
            operation=AnalysisOperation.STATISTICAL_TEST,
            description="Perform automated test selection (t-test, ANOVA, Mann-Whitney U, Chi-Square) and compute p-value",
            computation_type=ComputationType.HYPOTHESIS_TEST,
            data_requirement_ids=["req_sample_data"],
        )
        return [task], [req], [
            "Test statistic and degrees of freedom",
            "p-value and statistical significance conclusion (alpha = 0.05)",
            "Sample means and variance spread",
            "Group comparison details and effect sizes",
        ]

    def execute(
        self,
        task: AnalysisTask,
        rows: List[Dict[str, Any]],
        numeric_cols: List[str],
        dimension_cols: List[str],
    ) -> AnalysisTaskResult:
        from app.services.analysis.engines import StatisticalTestingEngine

        findings = []
        metrics: Dict[str, Any] = {}

        if rows:
            metric_col = numeric_cols[0] if numeric_cols else None
            group_col = dimension_cols[0] if dimension_cols else None
            second_cat = dimension_cols[1] if len(dimension_cols) > 1 and not metric_col else None

            test_res = StatisticalTestingEngine.auto_test(
                rows=rows,
                metric_col=metric_col,
                group_col=group_col,
                second_cat_col=second_cat,
            )

            metrics = {
                "test_name": test_res.get("test"),
                "is_significant": test_res.get("is_significant", False),
                "p_value": test_res.get("p_value"),
                "t_statistic": test_res.get("t_statistic"),
                "f_statistic": test_res.get("f_statistic"),
                "chi2_statistic": test_res.get("chi2_statistic"),
            }
            findings = StatisticalTestingEngine.generate_findings(test_res)

        return AnalysisTaskResult(
            task_id=task.task_id,
            name=task.name,
            computed_metrics=metrics,
            findings=findings,
        )


# --- From trend.py ---
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
        from app.services.analysis.engines import TrendEngine

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
