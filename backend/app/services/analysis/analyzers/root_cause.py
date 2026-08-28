"""Root Cause Analyzer: investigates drivers and underlying contributors to anomalies or performance drops."""
from typing import Any, Dict, List, Tuple

from app.services.analysis.analyzers.base import BaseAnalysisAnalyzer
from app.services.analysis.models import (
    AnalysisTask,
    AnalysisTaskResult,
    ComputationType,
    DataRetrievalRequirement,
)
from app.agent.semantic.models import AnalysisOperation, QuerySpec


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
        from app.services.analysis.engines.root_cause import RootCauseEngine

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
