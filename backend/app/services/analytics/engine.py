"""Analytics Engine — orchestrates targeted deterministic and domain analyzers over SQL result sets."""
import time
from typing import Any, Dict, List, Optional, Union

from app.services.analytics.models import AnalyticsResult, DatasetSummary
from app.services.analytics.analyzers import BaseAnalyzer
from app.services.analytics.analyzers import DatasetSummaryAnalyzer
from app.services.analytics.analyzers import NumericAnalyzer
from app.services.analytics.analyzers import CategoricalAnalyzer
from app.services.analysis.registry import ANALYSIS_REGISTRY, AnalysisStrategyRegistry
from app.services.analysis.models import AnalysisPlan, AnalysisTask
from app.agent.semantic.models import AnalysisOperation, QuerySpec
from app.utils.helpers import AnalysisType


class AnalyticsEngine:
    """
    Targeted & Deterministic Analytics Engine.
    Selectively executes modular analyzers based on the query's AnalysisPlan,
    minimizing computation, memory overhead, and token cost.
    """

    def __init__(self):
        self.summary_analyzer = DatasetSummaryAnalyzer()
        self.numeric_analyzer = NumericAnalyzer()
        self.categorical_analyzer = CategoricalAnalyzer()
        self.custom_analyzers: List[BaseAnalyzer] = []

    def register_analyzer(self, analyzer: BaseAnalyzer) -> None:
        """Register a custom analyzer to extend the analytics engine pipeline."""
        if isinstance(analyzer, BaseAnalyzer):
            self.custom_analyzers.append(analyzer)

    def analyze(
        self,
        rows: List[Dict[str, Any]],
        analysis_plan: Optional[Union[AnalysisPlan, QuerySpec, str]] = None,
    ) -> AnalyticsResult:
        """
        Execute targeted analytics over query result rows driven by the AnalysisPlan.

        Args:
            rows: SQL query result set formatted as a list of dictionaries.
            analysis_plan: Optional AnalysisPlan, QuerySpec, or analysis_type string defining targeted operations.

        Returns:
            AnalyticsResult: Structured object containing only the relevant analytical findings and stats.
        """
        start_time = time.time()

        if not rows:
            return AnalyticsResult(
                dataset=DatasetSummary(),
                numeric_stats={},
                categorical_stats={},
                analytical_findings=["No data rows returned for analysis."],
                execution_time_ms=0.0,
            )

        # 1. Dataset metadata (fast base profiling)
        dataset_summary = self.summary_analyzer.analyze(rows)

        executed_analyzers: List[str] = ["DatasetSummaryAnalyzer"]
        numeric_stats = {}
        categorical_stats = {}
        analytical_findings: List[str] = []
        task_results: List[Dict[str, Any]] = []

        # 2. Targeted Execution based on AnalysisPlan / Intent
        if analysis_plan is not None:
            plan_obj: Optional[AnalysisPlan] = None
            if isinstance(analysis_plan, AnalysisPlan):
                plan_obj = analysis_plan
            elif isinstance(analysis_plan, QuerySpec):
                plan_obj = AnalysisStrategyRegistry.build_plan_for_spec(analysis_plan)
            elif isinstance(analysis_plan, str):
                from app.agent.semantic.models import infer_analysis_profile
                profile = infer_analysis_profile(analysis_plan)
                dummy_spec = QuerySpec(
                    raw_question=analysis_plan,
                    analysis_required=profile["analysis_required"],
                    analysis_level=profile["analysis_level"],
                    operations=profile["operations"],
                )
                plan_obj = AnalysisStrategyRegistry.build_plan_for_spec(dummy_spec)

            analysis_type_name = (
                plan_obj.analysis_type.value
                if plan_obj and hasattr(plan_obj.analysis_type, "value")
                else (str(plan_obj.analysis_type) if plan_obj else "unknown")
            )

            # Extract numeric and dimension columns
            numeric_cols = dataset_summary.numeric_columns
            dimension_cols = dataset_summary.date_columns + dataset_summary.categorical_columns

            if plan_obj and plan_obj.tasks:
                # Execute each task via registered domain analyzer
                for task in plan_obj.tasks:
                    analyzer_cls = AnalysisStrategyRegistry.get(task.operation)
                    analyzer_name = analyzer_cls.__name__
                    if analyzer_name not in executed_analyzers:
                        executed_analyzers.append(analyzer_name)

                    try:
                        analyzer = analyzer_cls()
                        t_res = analyzer.execute(task, rows, numeric_cols, dimension_cols)
                        task_results.append(t_res.model_dump())
                        if t_res.findings:
                            analytical_findings.extend(t_res.findings)
                    except Exception as e:
                        task_results.append({"task_id": task.task_id, "status": "failed", "error": str(e)})

                # Run numeric summary only if needed by analytical operations
                needs_numeric = any(
                    t.operation in (
                        AnalysisOperation.AGGREGATE,
                        AnalysisOperation.ANOMALY,
                        AnalysisOperation.CORRELATION,
                        AnalysisOperation.STATISTICAL_TEST,
                    )
                    for t in plan_obj.tasks
                ) or plan_obj.analysis_type in (
                    AnalysisType.AGGREGATION,
                    AnalysisType.ANOMALY_DETECTION,
                    AnalysisType.EXPLORATORY_ANALYSIS,
                )

                if needs_numeric and dataset_summary.numeric_columns:
                    numeric_stats = self.numeric_analyzer.analyze(rows, dataset_summary)
                    executed_analyzers.append("NumericAnalyzer")

                # Run categorical summary only if needed by analytical operations
                needs_categorical = any(
                    t.operation in (
                        AnalysisOperation.DISTRIBUTION,
                        AnalysisOperation.SEGMENT,
                        AnalysisOperation.ROOT_CAUSE,
                    )
                    for t in plan_obj.tasks
                ) or plan_obj.analysis_type in (
                    AnalysisType.DISTRIBUTION,
                    AnalysisType.SEGMENTATION,
                    AnalysisType.ROOT_CAUSE,
                    AnalysisType.EXPLORATORY_ANALYSIS,
                )

                if needs_categorical and dataset_summary.categorical_columns:
                    categorical_stats = self.categorical_analyzer.analyze(rows, dataset_summary)
                    executed_analyzers.append("CategoricalAnalyzer")

            else:
                # Fallback if no tasks defined
                numeric_stats = self.numeric_analyzer.analyze(rows, dataset_summary)
                executed_analyzers.append("NumericAnalyzer")

        else:
            # 3. Default full profiling mode (when no specific analysis plan is provided)
            analysis_type_name = "profiling"
            numeric_stats = self.numeric_analyzer.analyze(rows, dataset_summary)
            executed_analyzers.append("NumericAnalyzer")

            categorical_stats = self.categorical_analyzer.analyze(rows, dataset_summary)
            executed_analyzers.append("CategoricalAnalyzer")

        # 4. Custom analyzers execution (if any registered)
        for custom_analyzer in self.custom_analyzers:
            try:
                custom_analyzer.analyze(rows, dataset_summary)
                executed_analyzers.append(custom_analyzer.__class__.__name__)
            except Exception:
                pass

        execution_time_ms = (time.time() - start_time) * 1000

        return AnalyticsResult(
            dataset=dataset_summary,
            numeric_stats=numeric_stats,
            categorical_stats=categorical_stats,
            analytical_findings=analytical_findings,
            analysis_type=analysis_type_name,
            executed_analyzers=executed_analyzers,
            task_results=task_results,
            execution_time_ms=round(execution_time_ms, 2),
        )
