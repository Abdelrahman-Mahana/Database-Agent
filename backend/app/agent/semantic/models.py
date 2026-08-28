"""Data models for Semantic Query Understanding."""
import re
from enum import Enum
from typing import Any, List, Dict, Optional
from pydantic import BaseModel, Field
from app.utils.text_processor import AnalysisType


class AnalysisLevel(str, Enum):
    """Depth of analysis required for the question."""
    RETRIEVAL = "retrieval"
    METRIC = "metric"
    INSIGHT = "insight"


class AnalysisOperation(str, Enum):
    """Analytical operations required to answer the question."""
    AGGREGATE = "aggregate"
    COMPARE = "compare"
    TREND = "trend"
    DISTRIBUTION = "distribution"
    CORRELATION = "correlation"
    ANOMALY = "anomaly_detection"
    SEGMENT = "segmentation"
    ROOT_CAUSE = "root_cause"
    FORECAST = "forecasting"
    STATISTICAL_TEST = "statistical_test"
    DATA_QUALITY = "data_quality"


class FilterCondition(BaseModel):
    """Semantic filter condition extracted from user question."""
    column: Optional[str] = None
    operator: str = "="
    value: Any = None
    raw_expression: str = ""


class SortCondition(BaseModel):
    """Sorting specification extracted from user question."""
    column: Optional[str] = None
    direction: str = "DESC"


class OutputFormat(str, Enum):
    """Expected output structure for the user query."""
    SCALAR = "scalar"
    LIST = "list"
    TABLE = "table"
    RANKING = "ranking"
    TIME_SERIES = "time_series"


class IntentType(str, Enum):
    """High-level domain intent kept for backward compatibility."""
    DATABASE = "database"
    SCHEMA = "schema"
    OFF_TOPIC = "off_topic"
    GREETING = "greeting"


class ExecutionRoute(str, Enum):
    """Controls which internal capability should handle the user request."""
    CONVERSATION = "conversation"
    SCHEMA = "schema"
    DATA_QUERY = "data_query"
    TOOLS = "tools"


class UnderstandingConfidence(BaseModel):
    """Decomposed confidence signals for rule-based QuerySpec understanding."""
    route_confidence: float = 0.0
    entity_confidence: float = 0.0
    metric_confidence: float = 0.0
    filter_confidence: float = 0.0
    time_confidence: float = 0.0
    aggregation_confidence: float = 0.0
    ambiguity_penalty: float = 0.0
    overall: float = 0.0


def infer_analysis_profile(
    question: str,
    analysis_type: AnalysisType = AnalysisType.UNKNOWN,
    aggregations: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Infer analytical concepts (analysis_required, analysis_level, analysis_goal, operations, comparisons, etc.)
    from the natural language question and detected analysis type.
    """
    q_clean = (question or "").strip()
    q_lower = q_clean.lower()
    aggregations = aggregations or []

    operations: List[AnalysisOperation] = []
    comparisons: List[str] = []
    statistical_methods: List[str] = []
    expected_findings: List[str] = []
    constraints: List[str] = []
    analysis_goal: Optional[str] = None

    # 1. Insight triggers (Deep analytical reasoning, diagnostics, predictions, correlations, anomalies)
    is_insight = False

    # Check analytical / performance / deep dive / exploratory keywords
    if analysis_type == AnalysisType.EXPLORATORY_ANALYSIS or re.search(r"\b(analyze|analysis|deep dive|performance|evaluate|evaluation|explore|exploratory|overview|breakdown|حلل|تحليل|أداء|اداء|تقييم|دراسة|استكشف|استكشاف|تشريح|نظرة عامة)\b", q_lower):
        is_insight = True
        operations.append(AnalysisOperation.SEGMENT)
        analysis_goal = f"Analyze performance and behavioral distribution for: {q_clean}"

    # Check root cause / explanatory
    if analysis_type == AnalysisType.ROOT_CAUSE or re.search(r"\b(why|reason|root cause|impact|cause|because|لماذا|ليه|سبب|أسباب|تأثير|انخفضت|هبطت|تراجعت)\b", q_lower):
        is_insight = True
        if AnalysisOperation.ROOT_CAUSE not in operations:
            operations.append(AnalysisOperation.ROOT_CAUSE)
        analysis_goal = analysis_goal or f"Investigate root cause and drivers for: {q_clean}"

    # Check comparison
    if analysis_type == AnalysisType.COMPARISON or re.search(r"\b(compare|comparison|versus|vs\.?|difference between|قارن|مقارنة|الفرق بين|مقابل|ضد)\b", q_lower):
        is_insight = True
        if AnalysisOperation.COMPARE not in operations:
            operations.append(AnalysisOperation.COMPARE)
        years = re.findall(r"(?:19\d\d|20\d\d)", q_clean)
        if len(years) >= 2:
            comparisons.append(f"{years[0]} vs {years[1]}")
        analysis_goal = analysis_goal or f"Compare metrics across dimensions: {q_clean}"

    # Check correlation / relationship
    if analysis_type == AnalysisType.CORRELATION or re.search(r"\b(correlation|correlate|relationship between|relate|علاقة|ارتباط|تأثير متبادل)\b", q_lower):
        is_insight = True
        if AnalysisOperation.CORRELATION not in operations:
            operations.append(AnalysisOperation.CORRELATION)
        statistical_methods.append("pearson_correlation")
        analysis_goal = analysis_goal or f"Evaluate correlation and relationship between variables: {q_clean}"

    # Check anomaly / outlier detection
    if analysis_type == AnalysisType.ANOMALY_DETECTION or re.search(r"\b(anomaly|anomalies|outlier|outliers|abnormal|unusual|شاذة|قيم شاذة|انحراف|شذوذ|غير طبيعي|غير معتاد)\b", q_lower):
        is_insight = True
        if AnalysisOperation.ANOMALY not in operations:
            operations.append(AnalysisOperation.ANOMALY)
        statistical_methods.append("z_score_outlier_detection")
        analysis_goal = analysis_goal or f"Identify anomalies and statistical outliers in: {q_clean}"

    # Check forecasting / prediction
    if analysis_type == AnalysisType.FORECASTING or re.search(r"\b(forecast|predict|projection|next month|next year|توقع|تنبؤ|المستقبل|القادم|الشهر القادم|السنة القادمة)\b", q_lower):
        is_insight = True
        if AnalysisOperation.FORECAST not in operations:
            operations.append(AnalysisOperation.FORECAST)
        statistical_methods.append("linear_trend_forecasting")
        analysis_goal = analysis_goal or f"Forecast future trajectory for: {q_clean}"

    # Check statistical tests
    if analysis_type == AnalysisType.STATISTICAL_TEST or re.search(r"\b(statistical test|hypothesis|t-test|chi-square|p-value|variance|standard deviation|stddev|انحراف معياري|تباين|اختبار إحصائي|دلالة إحصائية|فرضية)\b", q_lower):
        is_insight = True
        if AnalysisOperation.STATISTICAL_TEST not in operations:
            operations.append(AnalysisOperation.STATISTICAL_TEST)
        statistical_methods.append("hypothesis_testing")
        analysis_goal = analysis_goal or f"Perform statistical hypothesis testing for: {q_clean}"

    # Check data quality
    if analysis_type == AnalysisType.DATA_QUALITY or re.search(r"\b(data quality|missing values|null values|nulls|duplicates|inconsistency|جودة البيانات|قيم فارغة|قيم مفقودة|سجلات مكررة|تكرار)\b", q_lower):
        is_insight = True
        if AnalysisOperation.DATA_QUALITY not in operations:
            operations.append(AnalysisOperation.DATA_QUALITY)
        analysis_goal = analysis_goal or f"Audit data quality, nulls, and integrity for: {q_clean}"

    # Check segmentation
    if analysis_type == AnalysisType.SEGMENTATION or re.search(r"\b(segment|segments|segmentation|cohort|cohorts|cluster|clusters|rfm|شرائح|شريحة|تقسيم العملاء|تصنيف العملاء)\b", q_lower):
        is_insight = True
        if AnalysisOperation.SEGMENT not in operations:
            operations.append(AnalysisOperation.SEGMENT)
        analysis_goal = analysis_goal or f"Segment and cluster records for: {q_clean}"

    # Check trend / time-series trajectory
    if analysis_type == AnalysisType.TREND or re.search(r"\b(trend|trends|over time|year over year|month over month|growth rate|اتجاه|مسار|بمرور الوقت|عبر الزمن|نمو|تطور)\b", q_lower):
        is_insight = True
        if AnalysisOperation.TREND not in operations:
            operations.append(AnalysisOperation.TREND)
        analysis_goal = analysis_goal or f"Track temporal trends and growth rate for: {q_clean}"

    # Check distribution
    if analysis_type == AnalysisType.DISTRIBUTION or re.search(r"\b(distribution|distributed|breakdown by|spread|توزيع|حسب الدولة|حسب المنطقة|حسب الفئة)\b", q_lower):
        if AnalysisOperation.DISTRIBUTION not in operations:
            operations.append(AnalysisOperation.DISTRIBUTION)

    # 2. Assign Level and Required flag
    if is_insight:
        analysis_level = AnalysisLevel.INSIGHT
        analysis_required = True
        if not operations:
            operations.append(AnalysisOperation.AGGREGATE)
    elif aggregations or analysis_type in (AnalysisType.COUNT, AnalysisType.AGGREGATION, AnalysisType.RANKING, AnalysisType.DISTRIBUTION):
        analysis_level = AnalysisLevel.METRIC
        analysis_required = False
        if not operations:
            operations.append(AnalysisOperation.AGGREGATE)
    else:
        analysis_level = AnalysisLevel.RETRIEVAL
        analysis_required = False

    return {
        "analysis_required": analysis_required,
        "analysis_level": analysis_level,
        "analysis_goal": analysis_goal,
        "operations": operations,
        "comparisons": comparisons,
        "statistical_methods": statistical_methods,
        "expected_findings": expected_findings,
        "constraints": constraints,
    }


class QuerySpec(BaseModel):
    """
    Unified Semantic Query Specification.
    Consolidates Intent Classification, Semantic Parsing, Analytical Profiling,
    and Execution Planning into a single representation.
    """
    raw_question: str
    intent: IntentType = IntentType.DATABASE
    route: ExecutionRoute = ExecutionRoute.CONVERSATION
    route_confidence: float = 0.0
    off_topic_reason: Optional[str] = None
    off_topic_response: Optional[str] = None
    requires_clarification: bool = False
    clarification_prompt: Optional[str] = None
    ambiguity_candidates: List[str] = Field(default_factory=list)
    ambiguity_evidence: Optional[str] = None

    # Semantic Query Understanding
    analysis_type: AnalysisType = AnalysisType.UNKNOWN
    entities: List[str] = Field(default_factory=list)
    metrics: List[str] = Field(default_factory=list)
    target_metrics: List[Any] = Field(default_factory=list)
    dimensions: List[str] = Field(default_factory=list)
    filters: List[FilterCondition] = Field(default_factory=list)
    time_expressions: List[str] = Field(default_factory=list)
    aggregations: List[str] = Field(default_factory=list)
    sorting: List[SortCondition] = Field(default_factory=list)
    limit: Optional[int] = None
    expected_output: OutputFormat = OutputFormat.TABLE

    # Advanced Analytical Concepts
    analysis_required: bool = False
    analysis_level: AnalysisLevel = AnalysisLevel.RETRIEVAL
    analysis_goal: Optional[str] = None
    operations: List[AnalysisOperation] = Field(default_factory=list)
    comparisons: List[str] = Field(default_factory=list)
    statistical_methods: List[str] = Field(default_factory=list)
    expected_findings: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)

    # Planning & Multi-step Execution
    requires_multi_step: bool = False
    plan_steps: List[str] = Field(default_factory=list)

    # Observability & Metadata
    confidence: float = 1.0
    understanding_confidence: Optional[UnderstandingConfidence] = None
    source: str = "deterministic"
    business_goal: Optional[str] = None
    semantic_contract: Optional[Any] = None

    @property
    def output_shape(self) -> str:
        return self.expected_output.value if hasattr(self.expected_output, "value") else str(self.expected_output)

    @property
    def semantic_intent_hash(self) -> str:
        """Deterministic fingerprint representing the semantic intent and constraints."""
        if self.semantic_contract is not None and getattr(self.semantic_contract, "contract_hash", None):
            return self.semantic_contract.contract_hash
        import hashlib
        import json
        payload = {
            "entities": sorted([e.lower() for e in self.entities]),
            "metrics": sorted([m.lower() for m in self.metrics]),
            "dimensions": sorted([d.lower() for d in self.dimensions]),
            "analysis_type": str(self.analysis_type.value if hasattr(self.analysis_type, "value") else self.analysis_type),
            "aggregations": sorted([a.lower() for a in self.aggregations]),
            "filters": sorted([f"{f.column}:{f.operator}:{f.value}" for f in self.filters]),
            "sorting": sorted([f"{s.column}:{s.direction}" for s in self.sorting]),
            "limit": self.limit,
            "expected_output": self.output_shape,
        }
        serialized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    def to_semantic_contract(self, schema: Optional[Dict[str, Any]] = None) -> Any:
        """Build or return the frozen SemanticContract for this QuerySpec."""
        if self.semantic_contract is not None:
            return self.semantic_contract
        from app.agent.semantic.contract_builder import semantic_contract_builder
        contract = semantic_contract_builder.build_contract(
            question=self.raw_question,
            schema=schema,
            candidate_tables=self.entities,
            raw_entities=self.entities,
            raw_metrics=self.metrics,
            raw_dimensions=self.dimensions,
            raw_filters=self.filters,
            raw_sorting=self.sorting,
            limit=self.limit,
            intent=self.intent.value if hasattr(self.intent, "value") else str(self.intent),
            route=self.route.value if hasattr(self.route, "value") else str(self.route),
            analysis_type=self.analysis_type.value if hasattr(self.analysis_type, "value") else str(self.analysis_type),
            requires_clarification=self.requires_clarification,
            clarification_prompt=self.clarification_prompt,
            ambiguity_candidates=self.ambiguity_candidates,
        )
        self.semantic_contract = contract
        return contract

    def to_query_understanding(self) -> "QuerySpec":
        """Return self for seamless backward compatibility."""
        return self


# Backward-compatible alias for existing code
QueryUnderstanding = QuerySpec

