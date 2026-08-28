"""Analysis Registry: extensible mapping of analytical operations to dedicated analyzers."""
import logging
from typing import Dict, List, Optional, Type, Union

from app.services.analysis.analyzers import (
    AggregationAnalyzer,
    AnomalyAnalyzer,
    BaseAnalysisAnalyzer,
    ComparisonAnalyzer,
    CorrelationAnalyzer,
    DataQualityAnalyzer,
    DistributionAnalyzer,
    ExploratoryAnalyzer,
    ForecastingAnalyzer,
    RootCauseAnalyzer,
    SegmentationAnalyzer,
    StatisticalTestAnalyzer,
    TrendAnalyzer,
)
from app.services.analysis.models import (
    AnalysisPlan,
    AnalysisTask,
    DataRetrievalRequirement,
)
from app.agent.semantic.models import AnalysisLevel, AnalysisOperation, QuerySpec
from app.utils.text_processor import AnalysisType

logger = logging.getLogger(__name__)

# Extensible registry mapping operation names and analysis types to analyzer classes
ANALYSIS_REGISTRY: Dict[str, Type[BaseAnalysisAnalyzer]] = {
    # Operations
    "aggregate": AggregationAnalyzer,
    "aggregation": AggregationAnalyzer,
    "compare": ComparisonAnalyzer,
    "comparison": ComparisonAnalyzer,
    "trend": TrendAnalyzer,
    "distribution": DistributionAnalyzer,
    "correlation": CorrelationAnalyzer,
    "anomaly_detection": AnomalyAnalyzer,
    "anomaly": AnomalyAnalyzer,
    "segmentation": SegmentationAnalyzer,
    "segment": SegmentationAnalyzer,
    "root_cause": RootCauseAnalyzer,
    "forecasting": ForecastingAnalyzer,
    "forecast": ForecastingAnalyzer,
    "statistical_test": StatisticalTestAnalyzer,
    "data_quality": DataQualityAnalyzer,
    "exploratory_analysis": ExploratoryAnalyzer,
    # Common retrieval types fall back cleanly to AggregationAnalyzer
    "lookup": AggregationAnalyzer,
    "count": AggregationAnalyzer,
    "ranking": AggregationAnalyzer,
    "unknown": AggregationAnalyzer,
}


class AnalysisStrategyRegistry:
    """Provides extensible registration, retrieval, and automated planning via registered analyzers."""

    @classmethod
    def register(cls, key: str, analyzer_cls: Type[BaseAnalysisAnalyzer]) -> None:
        """Dynamically register a new analyzer without modifying core orchestration."""
        clean_key = str(key).lower().strip()
        ANALYSIS_REGISTRY[clean_key] = analyzer_cls
        logger.info("Registered custom analyzer %s under key '%s'", analyzer_cls.__name__, clean_key)

    @classmethod
    def get(cls, key: Union[str, AnalysisOperation, AnalysisType]) -> Type[BaseAnalysisAnalyzer]:
        """Look up the registered analyzer class for a given key, operation, or analysis type."""
        raw_key = key.value if hasattr(key, "value") else str(key)
        clean_key = raw_key.lower().strip()
        return ANALYSIS_REGISTRY.get(clean_key, AggregationAnalyzer)

    @classmethod
    def build_plan_for_spec(cls, spec: QuerySpec) -> AnalysisPlan:
        """Create a structured AnalysisPlan by delegating to registered analyzers."""
        q = spec.raw_question
        analysis_type = spec.analysis_type
        operations = spec.operations or []
        goal = spec.analysis_goal or spec.business_goal or f"Perform analytical investigation for: {q}"

        tasks: List[AnalysisTask] = []
        data_reqs: List[DataRetrievalRequirement] = []
        expected_insights: List[str] = list(spec.expected_findings)
        constraints: List[str] = list(spec.constraints)

        # 1. Check if exploratory analysis applies
        if (
            analysis_type == AnalysisType.EXPLORATORY_ANALYSIS
            or (AnalysisOperation.SEGMENT in operations and AnalysisOperation.TREND in operations)
        ):
            analyzer_cls = cls.get("exploratory_analysis")
            analyzer = analyzer_cls()
            t_list, r_list, i_list = analyzer.plan_tasks(spec)
            tasks.extend(t_list)
            data_reqs.extend(r_list)
            expected_insights.extend(i_list)

        # 2. Check if primary analysis_type is registered
        elif analysis_type.value in ANALYSIS_REGISTRY and analysis_type != AnalysisType.UNKNOWN:
            analyzer_cls = cls.get(analysis_type.value)
            analyzer = analyzer_cls()
            t_list, r_list, i_list = analyzer.plan_tasks(spec)
            tasks.extend(t_list)
            data_reqs.extend(r_list)
            expected_insights.extend(i_list)

        # 3. Check registered operations in spec
        elif operations:
            for op in operations:
                analyzer_cls = cls.get(op.value if hasattr(op, "value") else str(op))
                analyzer = analyzer_cls()
                t_list, r_list, i_list = analyzer.plan_tasks(spec)
                tasks.extend(t_list)
                data_reqs.extend(r_list)
                expected_insights.extend(i_list)

        # 4. Fallback to default AggregationAnalyzer
        else:
            analyzer = AggregationAnalyzer()
            t_list, r_list, i_list = analyzer.plan_tasks(spec)
            tasks.extend(t_list)
            data_reqs.extend(r_list)
            expected_insights.extend(i_list)

        return AnalysisPlan(
            question=q,
            analysis_required=spec.analysis_required,
            analysis_level=spec.analysis_level,
            analysis_type=spec.analysis_type,
            analysis_goal=goal,
            tasks=tasks,
            data_requirements=data_reqs,
            expected_insights=expected_insights,
            constraints=constraints,
            requires_multi_step=len(data_reqs) > 1 or spec.requires_multi_step,
            source="analysis_strategy_registry",
        )
