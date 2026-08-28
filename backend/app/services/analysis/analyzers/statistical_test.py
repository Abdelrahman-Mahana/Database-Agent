"""Statistical Test Analyzer: evaluates hypothesis tests, variance, and standard deviation."""
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
        from app.services.analysis.engines.statistical_testing import StatisticalTestingEngine

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
