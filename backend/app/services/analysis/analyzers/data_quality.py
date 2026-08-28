"""Data Quality Analyzer: checks for nulls, missing values, duplicates, and data anomalies."""
from typing import Any, Dict, List, Tuple

from app.services.analysis.analyzers.base import BaseAnalysisAnalyzer
from app.services.analysis.models import (
    AnalysisTask,
    AnalysisTaskResult,
    ComputationType,
    DataRetrievalRequirement,
)
from app.agent.semantic.models import AnalysisOperation, QuerySpec


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
        from app.services.analysis.engines.data_quality import DataQualityEngine

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
