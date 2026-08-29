"""Data models for Semantic Query Understanding."""
import re
from enum import Enum
from typing import Any, List, Dict, Optional
from pydantic import BaseModel, Field
from app.utils.helpers import AnalysisType


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




from enum import Enum
from loguru import logger
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from typing import Any, Dict, List, Optional, Tuple, Set
import hashlib
import json
import re
import uuid

# --- From contract.py ---
class GrainType(str, Enum):
    """The mathematical granularity of the query output."""
    SCALAR = "scalar"                    # Exactly 1 aggregate value (e.g. Total Revenue, Total Count)
    ENTITY_GRAIN = "entity"              # 1 row per primary entity instance (e.g. 1 row per customer)
    TEMPORAL_GRAIN = "temporal"          # 1 row per time period (e.g. 1 row per month, 1 row per year)
    MULTIDIMENSIONAL = "multidimensional"  # 1 row per combination of dimensions (e.g. Country x Year)
    LIST_GRAIN = "list"                  # Unaggregated list of records / entities


class FormulaType(str, Enum):
    """Mathematical aggregation or formula type."""
    SUM = "sum"
    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    AVG = "avg"
    MIN = "min"
    MAX = "max"
    PERCENTAGE = "percentage"
    RATIO = "ratio"
    CUSTOM = "custom"


class SemanticGrain(BaseModel):
    """Specifies the logical and physical grain of the target output."""
    grain_type: GrainType = GrainType.ENTITY_GRAIN
    primary_entity: Optional[str] = None
    grain_keys: List[str] = Field(default_factory=list)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "grain_type": self.grain_type.value if hasattr(self.grain_type, "value") else str(self.grain_type),
            "primary_entity": self.primary_entity,
            "grain_keys": self.grain_keys,
            "description": self.description,
        }


class MetricSpec(BaseModel):
    """Formal business measure / metric definition."""
    metric_id: str
    display_name: str = ""
    formula_type: FormulaType = FormulaType.SUM
    expression: str = ""              # e.g. "Invoice.Total" or "InvoiceLine.UnitPrice * InvoiceLine.Quantity"
    source_table: Optional[str] = None
    source_column: Optional[str] = None
    requires_distinct: bool = False
    is_calculated: bool = False
    unit: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)

    def to_sql_projection(self, table_alias: Optional[str] = None) -> str:
        """Format as SQL expression snippet."""
        col = self.source_column or self.expression or "*"
        if table_alias and "." not in col and col != "*":
            target = f"{table_alias}.{col}"
        else:
            target = col

        if self.formula_type == FormulaType.SUM:
            return f"SUM({target})"
        elif self.formula_type == FormulaType.COUNT_DISTINCT:
            return f"COUNT(DISTINCT {target})"
        elif self.formula_type == FormulaType.COUNT:
            return f"COUNT({target})"
        elif self.formula_type == FormulaType.AVG:
            return f"AVG({target})"
        elif self.formula_type == FormulaType.MIN:
            return f"MIN({target})"
        elif self.formula_type == FormulaType.MAX:
            return f"MAX({target})"
        elif self.expression:
            return self.expression
        return target


class DimensionSpec(BaseModel):
    """Grouping dimension or attribute specification."""
    dimension_id: str
    display_name: str = ""
    source_table: Optional[str] = None
    source_column: Optional[str] = None
    temporal_grain: Optional[str] = None  # e.g. "YEAR", "MONTH", "DAY"
    is_primary_key: bool = False
    aliases: List[str] = Field(default_factory=list)

    def to_sql_column(self, table_alias: Optional[str] = None) -> str:
        col = self.source_column or self.dimension_id
        if table_alias and "." not in col:
            return f"{table_alias}.{col}"
        return col


class TimeSpec(BaseModel):
    """Normalized temporal scope and boundary conditions."""
    time_column: Optional[str] = None
    source_table: Optional[str] = None
    start_date: Optional[str] = None      # ISO format: "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS"
    end_date: Optional[str] = None        # ISO format: "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM:SS"
    granularity: Optional[str] = None    # "YEAR", "QUARTER", "MONTH", "WEEK", "DAY"
    raw_expression: str = ""             # Original phrase e.g. "in 2012", "last month", "في عام 2023"
    is_relative: bool = False
    comparison_start_date: Optional[str] = None
    comparison_end_date: Optional[str] = None

    @property
    def has_bounds(self) -> bool:
        return bool(self.start_date or self.end_date)


class FilterOperator(str, Enum):
    """Normalized filter comparison operators."""
    EQ = "="
    NEQ = "!="
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    IN = "IN"
    NOT_IN = "NOT IN"
    LIKE = "LIKE"
    ILIKE = "ILIKE"
    BETWEEN = "BETWEEN"
    IS_NULL = "IS NULL"
    IS_NOT_NULL = "IS NOT NULL"


class FilterSpec(BaseModel):
    """Typed and grounded filter condition."""
    concept: str = ""
    target_table: Optional[str] = None
    target_column: Optional[str] = None
    operator: FilterOperator = FilterOperator.EQ
    raw_value: Any = None
    normalized_value: Any = None
    data_type: str = "text"              # text, integer, float, date, boolean
    is_mandatory: bool = True
    raw_expression: str = ""

    def to_sql_predicate(self, table_alias: Optional[str] = None) -> str:
        col = self.target_column or self.concept
        if table_alias and "." not in col:
            col = f"{table_alias}.{col}"

        op = self.operator.value if hasattr(self.operator, "value") else str(self.operator)
        if op in ("IS NULL", "IS NOT NULL"):
            return f"{col} {op}"

        val = self.normalized_value if self.normalized_value is not None else self.raw_value
        if op in ("IN", "NOT IN") and isinstance(val, (list, tuple, set)):
            formatted = ", ".join(f"'{v}'" if isinstance(v, str) else str(v) for v in val)
            return f"{col} {op} ({formatted})"
        elif op == "BETWEEN" and isinstance(val, (list, tuple)) and len(val) >= 2:
            v1 = f"'{val[0]}'" if isinstance(val[0], str) else str(val[0])
            v2 = f"'{val[1]}'" if isinstance(val[1], str) else str(val[1])
            return f"{col} BETWEEN {v1} AND {v2}"
        elif isinstance(val, str):
            # Escape quotes
            val_escaped = val.replace("'", "''")
            if op in ("LIKE", "ILIKE"):
                return f"{col} {op} '%{val_escaped}%'"
            return f"{col} {op} '{val_escaped}'"
        elif val is not None:
            return f"{col} {op} {val}"
        return f"{col} IS NOT NULL"


class SortSpec(BaseModel):
    """Sorting specification."""
    target: str                          # Column or metric id
    direction: str = "DESC"              # "ASC" or "DESC"
    is_metric: bool = True


class SemanticContract(BaseModel):
    """
    Formal, Frozen Semantic Contract.
    
    Establishes the exact business semantics, grain, measures, dimensions,
    filters, time bounds, and answerability status before SQL generation.
    Once frozen, any mutation is forbidden, and the AST Validator proves
    that the generated SQL adheres 100% to this contract.
    """
    contract_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    raw_question: str
    normalized_question: str = ""
    intent: str = "database"             # "database", "schema", "conversation", "off_topic"
    route: str = "data_query"            # "data_query", "schema", "conversation", "tools"
    
    # Core Semantics
    primary_entity: Optional[str] = None
    grain: SemanticGrain = Field(default_factory=SemanticGrain)
    measures: List[MetricSpec] = Field(default_factory=list)
    dimensions: List[DimensionSpec] = Field(default_factory=list)
    time_spec: Optional[TimeSpec] = None
    filters: List[FilterSpec] = Field(default_factory=list)
    sorting: List[SortSpec] = Field(default_factory=list)
    limit: Optional[int] = None
    expected_output_shape: str = "table" # "scalar", "list", "table", "ranking", "time_series"
    analysis_type: str = "unknown"

    # Answerability & Ambiguity Controls
    is_answerable: bool = True
    unsupported_reason: Optional[str] = None
    requires_clarification: bool = False
    clarification_prompt: Optional[str] = None
    ambiguity_candidates: List[str] = Field(default_factory=list)
    ambiguity_evidence: Optional[str] = None

    # Quality & Observability
    confidence: float = 1.0
    confidence_breakdown: Dict[str, float] = Field(default_factory=dict)
    
    # Contract Freeze Status
    is_frozen: bool = False
    contract_hash: str = ""

    def freeze(self) -> "SemanticContract":
        """Freeze contract state and compute immutable cryptographic hash."""
        payload = {
            "question": self.normalized_question or self.raw_question,
            "intent": self.intent,
            "route": self.route,
            "primary_entity": (self.primary_entity or "").lower(),
            "grain": self.grain.to_dict(),
            "measures": sorted([
                f"{m.metric_id}:{m.formula_type.value if hasattr(m.formula_type, 'value') else m.formula_type}:{m.source_table or ''}.{m.source_column or ''}"
                for m in self.measures
            ]),
            "dimensions": sorted([
                f"{d.dimension_id}:{d.source_table or ''}.{d.source_column or ''}:{d.temporal_grain or ''}"
                for d in self.dimensions
            ]),
            "time_spec": {
                "col": self.time_spec.time_column if self.time_spec else None,
                "start": self.time_spec.start_date if self.time_spec else None,
                "end": self.time_spec.end_date if self.time_spec else None,
                "granularity": self.time_spec.granularity if self.time_spec else None,
            } if self.time_spec else None,
            "filters": sorted([
                f"{f.target_table or ''}.{f.target_column or f.concept}:{f.operator.value if hasattr(f.operator, 'value') else f.operator}:{f.normalized_value}"
                for f in self.filters
            ]),
            "sorting": sorted([f"{s.target}:{s.direction}" for s in self.sorting]),
            "limit": self.limit,
            "shape": self.expected_output_shape,
        }
        serialized = json.dumps(payload, sort_keys=True)
        self.contract_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
        self.is_frozen = True
        return self

    def summary(self) -> str:
        """Produce human-readable and LLM-friendly contract summary."""
        parts = [f"Semantic Contract [ID: {self.contract_id}, Hash: {self.contract_hash or 'unfrozen'}]"]
        if self.primary_entity:
            parts.append(f"  Primary Entity: {self.primary_entity}")
        parts.append(f"  Target Grain: {self.grain.grain_type.value if hasattr(self.grain.grain_type, 'value') else self.grain.grain_type} ({self.grain.description or 'default'})")
        
        if self.measures:
            m_strs = [f"{m.display_name or m.metric_id} ({m.formula_type.value if hasattr(m.formula_type, 'value') else m.formula_type} of {m.source_column or m.expression})" for m in self.measures]
            parts.append(f"  Measures ({len(self.measures)}): {', '.join(m_strs)}")
        
        if self.dimensions:
            d_strs = [f"{d.display_name or d.dimension_id} ({d.source_table or ''}.{d.source_column or ''})" for d in self.dimensions]
            parts.append(f"  Dimensions ({len(self.dimensions)}): {', '.join(d_strs)}")
        
        if self.time_spec and (self.time_spec.start_date or self.time_spec.raw_expression):
            parts.append(f"  Time Bounds: {self.time_spec.raw_expression} -> [{self.time_spec.start_date} to {self.time_spec.end_date}] on {self.time_spec.time_column or 'date'}")
        
        if self.filters:
            f_strs = [f.to_sql_predicate() for f in self.filters]
            parts.append(f"  Filters ({len(self.filters)}): {', '.join(f_strs)}")
        
        if self.sorting:
            s_strs = [f"{s.target} {s.direction}" for s in self.sorting]
            parts.append(f"  Sorting: {', '.join(s_strs)}")
            
        if self.limit:
            parts.append(f"  Limit: {self.limit}")
            
        parts.append(f"  Output Shape: {self.expected_output_shape}")
        return "\n".join(parts)


# --- From metric_registry.py ---
class BusinessMetricDefinition:
    """Enterprise definition for a business metric template."""

    def __init__(
        self,
        metric_id: str,
        display_name: str,
        display_name_ar: str,
        formula_type: FormulaType,
        aliases_en: List[str],
        aliases_ar: List[str],
        candidate_columns: List[str],
        candidate_tables: List[str],
        unit: Optional[str] = "currency",
        default_expression: str = "",
        description: str = "",
        is_composite: bool = False,
        composite_formula: Optional[str] = None,
        is_additive: bool = True,
        certified: bool = True,
    ):
        self.metric_id = metric_id
        self.display_name = display_name
        self.display_name_ar = display_name_ar
        self.formula_type = formula_type
        self.aliases_en = [a.lower() for a in aliases_en]
        self.aliases_ar = [a.lower() for a in aliases_ar]
        self.candidate_columns = [c.lower() for c in candidate_columns]
        self.candidate_tables = [t.lower() for t in candidate_tables]
        self.unit = unit
        self.default_expression = default_expression
        self.description = description
        self.is_composite = is_composite
        self.composite_formula = composite_formula
        self.is_additive = is_additive
        self.certified = certified

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "display_name": self.display_name,
            "display_name_ar": self.display_name_ar,
            "formula_type": self.formula_type.value if hasattr(self.formula_type, "value") else str(self.formula_type),
            "aliases_en": self.aliases_en,
            "aliases_ar": self.aliases_ar,
            "candidate_columns": self.candidate_columns,
            "candidate_tables": self.candidate_tables,
            "unit": self.unit,
            "description": self.description,
            "is_composite": self.is_composite,
            "certified": self.certified,
        }


class BusinessMetricRegistry:
    """
    Central repository of enterprise business metrics.
    Resolves natural language metric requests into concrete MetricSpec instances
    grounded in the active database schema without hardcoding column names in caller logic.
    """

    def __init__(self):
        self._definitions: Dict[str, BusinessMetricDefinition] = {}
        self._custom_definitions: Dict[str, BusinessMetricDefinition] = {}
        self._register_default_metrics()

    def _register_default_metrics(self):
        """Register canonical enterprise metric templates."""
        # 1. Total Revenue / Gross Sales
        self.register(BusinessMetricDefinition(
            metric_id="revenue",
            display_name="Total Revenue",
            display_name_ar="إجمالي الإيرادات",
            formula_type=FormulaType.SUM,
            aliases_en=["revenue", "sales", "total sales", "turnover", "total revenue", "income", "sales amount", "gross sales", "total income"],
            aliases_ar=["إيراد", "إيرادات", "مبيعات", "إجمالي المبيعات", "دخل", "المبيعات", "الإيرادات", "مبلغ المبيعات", "حجم المبيعات", "المردود"],
            candidate_columns=["total", "amount", "amount_total", "price", "unitprice", "line_total", "subtotal", "gross_amount", "sale_price"],
            candidate_tables=["invoices", "invoice", "account_move", "orders", "order", "sales", "sale_order", "invoice_line", "invoiceline", "payments"],
            unit="currency",
            description="Total gross monetary value generated from sales/invoices.",
        ))

        # 2. Net Revenue / Net Sales
        self.register(BusinessMetricDefinition(
            metric_id="net_revenue",
            display_name="Net Revenue",
            display_name_ar="صافي الإيرادات",
            formula_type=FormulaType.SUM,
            aliases_en=["net revenue", "net sales", "net income", "net amount"],
            aliases_ar=["صافي الإيرادات", "صافي المبيعات", "صافي الدخل", "المبيعات الصافية"],
            candidate_columns=["net_amount", "subtotal", "amount_untaxed", "total", "amount"],
            candidate_tables=["invoices", "invoice", "orders", "order", "sales"],
            unit="currency",
            description="Total revenue after discounts and returns.",
        ))

        # 3. Average Order / Invoice Value (AOV)
        self.register(BusinessMetricDefinition(
            metric_id="average_order_value",
            display_name="Average Order Value",
            display_name_ar="متوسط قيمة الفاتورة",
            formula_type=FormulaType.AVG,
            aliases_en=["average order value", "aov", "average sale", "average invoice", "avg spend", "average transaction", "mean order value"],
            aliases_ar=["متوسط الفاتورة", "متوسط المبيعات", "متوسط الطلب", "معدل الشراء", "متوسط قيمة الطلب", "متوسط المعاملة"],
            candidate_columns=["total", "amount", "amount_total", "price"],
            candidate_tables=["invoices", "invoice", "account_move", "orders", "order", "sales"],
            unit="currency",
            description="Average monetary value per transaction or invoice.",
        ))

        # 4. Order / Transaction Count
        self.register(BusinessMetricDefinition(
            metric_id="order_count",
            display_name="Order Count",
            display_name_ar="عدد الفواتير / الطلبات",
            formula_type=FormulaType.COUNT,
            aliases_en=["order count", "orders count", "number of orders", "invoice count", "invoices count", "number of invoices", "transaction count", "total orders", "total invoices"],
            aliases_ar=["عدد الطلبات", "عدد الفواتير", "عدد المعاملات", "حجم الطلبات", "إجمالي الطلبات", "إجمالي الفواتير", "كمية الطلبات"],
            candidate_columns=["invoiceid", "invoice_id", "orderid", "order_id", "id", "move_id"],
            candidate_tables=["invoices", "invoice", "account_move", "orders", "order", "sales"],
            unit="count",
            description="Total number of discrete orders or invoices.",
        ))

        # 5. Customer Count (Unique / Distinct)
        self.register(BusinessMetricDefinition(
            metric_id="customer_count",
            display_name="Customer Count",
            display_name_ar="عدد العملاء",
            formula_type=FormulaType.COUNT_DISTINCT,
            aliases_en=["customer count", "number of customers", "unique customers", "client count", "clients count", "total customers", "distinct customers"],
            aliases_ar=["عدد العملاء", "العملاء الفريدين", "حجم العملاء", "عدد الزبائن", "إجمالي العملاء", "المستخدمين"],
            candidate_columns=["customerid", "customer_id", "partner_id", "client_id", "user_id", "id"],
            candidate_tables=["customers", "customer", "res_partner", "users", "clients", "invoices", "orders"],
            unit="count",
            description="Count of distinct customers or accounts.",
        ))

        # 6. Active Customers
        self.register(BusinessMetricDefinition(
            metric_id="active_customers",
            display_name="Active Customers",
            display_name_ar="عدد العملاء النشطين",
            formula_type=FormulaType.COUNT_DISTINCT,
            aliases_en=["active customers", "active clients", "active users", "current customers"],
            aliases_ar=["العملاء النشطين", "الزبائن النشطين", "المستخدمين النشطين", "العملاء الحاليين"],
            candidate_columns=["customerid", "customer_id", "partner_id", "id"],
            candidate_tables=["invoices", "orders", "customers"],
            unit="count",
            description="Number of distinct customers with transactions.",
        ))

        # 7. Quantity Sold / Volume
        self.register(BusinessMetricDefinition(
            metric_id="quantity_sold",
            display_name="Quantity Sold",
            display_name_ar="الكمية المباعة",
            formula_type=FormulaType.SUM,
            aliases_en=["quantity sold", "units sold", "quantity", "total quantity", "volume", "total units"],
            aliases_ar=["الكمية المباعة", "عدد الوحدات المباعة", "إجمالي الكمية", "الكميات", "حجم المبيعات بالوحدات", "عدد القطع"],
            candidate_columns=["quantity", "qty", "units", "count", "product_uom_qty"],
            candidate_tables=["invoiceline", "invoice_line", "order_items", "order_line", "sales_lines"],
            unit="units",
            description="Total number of product units sold.",
        ))

        # 8. Item / Product / Track Count
        self.register(BusinessMetricDefinition(
            metric_id="item_count",
            display_name="Item Count",
            display_name_ar="عدد الأصناف / المنتجات",
            formula_type=FormulaType.COUNT,
            aliases_en=["item count", "number of items", "product count", "track count", "number of tracks", "number of songs", "catalog size"],
            aliases_ar=["عدد المنتجات", "عدد الأصناف", "عدد الأغاني", "عدد المسارات", "إجمالي الأصناف"],
            candidate_columns=["trackid", "track_id", "product_id", "item_id", "id"],
            candidate_tables=["tracks", "track", "products", "product_product", "items", "catalog"],
            unit="count",
            description="Total count of catalog products or items.",
        ))

        # 9. Gross Profit Margin
        self.register(BusinessMetricDefinition(
            metric_id="profit_margin",
            display_name="Profit Margin",
            display_name_ar="هامش الربح",
            formula_type=FormulaType.PERCENTAGE,
            aliases_en=["profit margin", "gross margin", "margin percentage", "margin pct", "margin"],
            aliases_ar=["هامش الربح", "نسبة الربح", "هامش المبيعات", "معدل الهامش"],
            candidate_columns=["margin", "profit_margin", "profit", "total"],
            candidate_tables=["sales", "invoices", "orders"],
            unit="percentage",
            description="Profit margin expressed as a percentage.",
            is_composite=True,
        ))

        # 10. Average Revenue Per User (ARPU)
        self.register(BusinessMetricDefinition(
            metric_id="arpu",
            display_name="Average Revenue Per User",
            display_name_ar="متوسط العائد لكل عميل",
            formula_type=FormulaType.RATIO,
            aliases_en=["arpu", "average revenue per user", "revenue per customer", "customer spend"],
            aliases_ar=["متوسط العائد لكل عميل", "عائد العميل", "متوسط دخل العميل"],
            candidate_columns=["total", "amount"],
            candidate_tables=["invoices", "orders", "customers"],
            unit="currency",
            description="Total revenue divided by unique customers.",
            is_composite=True,
        ))

        # 11. Discount Amount
        self.register(BusinessMetricDefinition(
            metric_id="discount_amount",
            display_name="Total Discount",
            display_name_ar="إجمالي الخصومات",
            formula_type=FormulaType.SUM,
            aliases_en=["discount", "total discount", "discounts", "discount amount", "rebates"],
            aliases_ar=["الخصم", "إجمالي الخصم", "قيمة الخصومات", "الخصومات", "التخفيضات"],
            candidate_columns=["discount", "discount_amount", "rebate"],
            candidate_tables=["invoiceline", "invoice_line", "order_items", "orders", "invoices"],
            unit="currency",
            description="Total monetary value of discounts applied.",
        ))

    def register(self, definition: BusinessMetricDefinition):
        """Register or override a business metric definition."""
        self._definitions[definition.metric_id] = definition

    def register_custom_metric(
        self,
        metric_id: str,
        display_name: str,
        display_name_ar: str,
        formula_type: FormulaType,
        aliases_en: List[str],
        aliases_ar: List[str],
        candidate_columns: List[str],
        candidate_tables: List[str],
        unit: Optional[str] = "currency",
        description: str = "",
    ) -> BusinessMetricDefinition:
        """Dynamically register a domain-specific custom business metric."""
        metric_def = BusinessMetricDefinition(
            metric_id=metric_id,
            display_name=display_name,
            display_name_ar=display_name_ar,
            formula_type=formula_type,
            aliases_en=aliases_en,
            aliases_ar=aliases_ar,
            candidate_columns=candidate_columns,
            candidate_tables=candidate_tables,
            unit=unit,
            description=description,
            certified=True,
        )
        self._custom_definitions[metric_id] = metric_def
        self._definitions[metric_id] = metric_def
        logger.info("Registered custom business metric: %s (%s)", metric_id, display_name)
        return metric_def

    def get_all_metrics(self) -> List[BusinessMetricDefinition]:
        """Return all registered metric definitions."""
        return list(self._definitions.values())

    def resolve_metrics(
        self,
        text: str,
        schema: Optional[Dict[str, Any]] = None,
        candidate_tables: Optional[List[str]] = None,
    ) -> List[MetricSpec]:
        """
        Extract and resolve ALL business metric concepts in natural language text (English/Arabic),
        grounding each against the active physical schema.
        """
        text_lower = (text or "").lower().strip()
        if not text_lower:
            return []

        resolved: List[MetricSpec] = []
        matched_ids: Set[str] = set()

        for mdef in self._definitions.values():
            if mdef.metric_id in matched_ids:
                continue

            # 1. Check exact word boundaries
            matched = False
            for alias in mdef.aliases_en:
                if re.search(rf"\b{re.escape(alias)}\b", text_lower):
                    matched = True
                    break

            if not matched:
                # 2. Check Arabic aliases and prefixed variants (e.g. "إجمالي الإيرادات", "كمية المبيعات")
                for alias in mdef.aliases_ar:
                    if alias in text_lower:
                        matched = True
                        break

            if matched:
                spec = self._ground_metric_definition(mdef, text, schema, candidate_tables)
                if spec:
                    resolved.append(spec)
                    matched_ids.add(mdef.metric_id)

        return resolved

    def resolve_metric(
        self,
        text: str,
        schema: Optional[Dict[str, Any]] = None,
        candidate_tables: Optional[List[str]] = None,
    ) -> Optional[MetricSpec]:
        """Resolve the primary single business metric in a natural language phrase."""
        specs = self.resolve_metrics(text, schema, candidate_tables)
        return specs[0] if specs else None

    def _ground_metric_definition(
        self,
        mdef: BusinessMetricDefinition,
        text: str,
        schema: Optional[Dict[str, Any]],
        candidate_tables: Optional[List[str]],
    ) -> MetricSpec:
        """Ground the abstract metric definition to physical tables and columns in schema."""
        source_table, source_column = self._ground_to_schema(
            mdef, schema, candidate_tables
        )

        display_name = (
            mdef.display_name_ar
            if any("\u0600" <= c <= "\u06FF" for c in text)
            else mdef.display_name
        )

        # Build canonical SQL formula representation
        if source_table and source_column:
            qualified_target = f"{source_table}.{source_column}"
        else:
            qualified_target = source_column or mdef.metric_id

        if mdef.formula_type == FormulaType.SUM:
            expression = f"SUM({qualified_target})"
        elif mdef.formula_type == FormulaType.AVG:
            expression = f"AVG({qualified_target})"
        elif mdef.formula_type == FormulaType.COUNT_DISTINCT:
            expression = f"COUNT(DISTINCT {qualified_target})"
        elif mdef.formula_type == FormulaType.COUNT:
            expression = f"COUNT({qualified_target})"
        elif mdef.formula_type == FormulaType.MIN:
            expression = f"MIN({qualified_target})"
        elif mdef.formula_type == FormulaType.MAX:
            expression = f"MAX({qualified_target})"
        elif mdef.formula_type == FormulaType.PERCENTAGE:
            expression = f"SUM({qualified_target}) * 100.0"
        else:
            expression = qualified_target

        return MetricSpec(
            metric_id=mdef.metric_id,
            display_name=display_name,
            formula_type=mdef.formula_type,
            source_table=source_table,
            source_column=source_column,
            expression=expression,
            requires_distinct=(mdef.formula_type == FormulaType.COUNT_DISTINCT),
            unit=mdef.unit,
            aliases=mdef.aliases_en + mdef.aliases_ar,
        )

    def _ground_to_schema(
        self,
        mdef: BusinessMetricDefinition,
        schema: Optional[Dict[str, Any]],
        candidate_tables: Optional[List[str]],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Identify the best matching table and column in schema."""
        if not schema:
            t = candidate_tables[0] if candidate_tables else (mdef.candidate_tables[0] if mdef.candidate_tables else None)
            c = mdef.candidate_columns[0] if mdef.candidate_columns else None
            return t, c

        schema_tables = {t.lower(): t for t in schema.keys()}

        # 1. Prioritize candidate tables from caller / context
        search_tables = []
        if candidate_tables:
            for ct in candidate_tables:
                if ct.lower() in schema_tables:
                    search_tables.append(schema_tables[ct.lower()])

        # 2. Check candidate tables registered in metric definition
        for ct in mdef.candidate_tables:
            if ct in schema_tables and schema_tables[ct] not in search_tables:
                search_tables.append(schema_tables[ct])

        # 3. If none matched, check all tables in schema
        if not search_tables:
            search_tables = list(schema.values()) if isinstance(next(iter(schema.values()), None), str) else list(schema.keys())

        # 4. Look for candidate columns in prioritized tables
        for table_name in search_tables:
            table_info = schema.get(table_name) or {}
            columns = []
            if isinstance(table_info, dict):
                columns = [col.get("name") if isinstance(col, dict) else str(col) for col in table_info.get("columns", [])]
            elif isinstance(table_info, list):
                columns = [c.get("name") if isinstance(c, dict) else str(c) for c in table_info]

            col_map = {c.lower(): c for c in columns}
            for candidate_col in mdef.candidate_columns:
                if candidate_col in col_map:
                    return table_name, col_map[candidate_col]

        # 5. If table exists but column was not found in schema, return table with None column
        for ct in mdef.candidate_tables:
            if ct in schema_tables:
                return schema_tables[ct], None

        return None, None


# Global registry singleton
business_metric_registry = BusinessMetricRegistry()
