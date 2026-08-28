"""Anomaly Analyzer: detects statistical outliers, unusual drops, spikes, and Z-score anomalies."""
import math
from typing import Any, Dict, List, Tuple

from app.services.analysis.analyzers.base import BaseAnalysisAnalyzer
from app.services.analysis.models import (
    AnalysisTask,
    AnalysisTaskResult,
    ComputationType,
    DataRetrievalRequirement,
)
from app.agent.semantic.models import AnalysisOperation, QuerySpec


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
        from app.services.analysis.engines.anomaly_detection import AnomalyDetectionEngine

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
