"""Correlation Analyzer: calculates Pearson correlation and directional association between variables."""
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
        from app.services.analysis.engines.correlation import CorrelationEngine

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
