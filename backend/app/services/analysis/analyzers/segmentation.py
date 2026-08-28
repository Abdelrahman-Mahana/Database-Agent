"""Segmentation Analyzer: clusters and ranks customer/entity cohorts based on behavioral metrics."""
from typing import Any, Dict, List, Tuple

from app.services.analysis.analyzers.base import BaseAnalysisAnalyzer
from app.services.analysis.models import (
    AnalysisTask,
    AnalysisTaskResult,
    ComputationType,
    DataRetrievalRequirement,
)
from app.agent.semantic.models import AnalysisOperation, QuerySpec


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
