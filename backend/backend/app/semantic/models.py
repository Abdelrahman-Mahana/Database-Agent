"""Data models for Semantic Query Understanding."""
from enum import Enum
from typing import Any, List, Dict, Optional
from pydantic import BaseModel, Field
from app.utils.text_processor import AnalysisType


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


class QuerySpec(BaseModel):
    """
    Unified Semantic Query Specification.
    Consolidates Intent Classification, Semantic Parsing, and Execution Planning into a single representation.
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
    dimensions: List[str] = Field(default_factory=list)
    filters: List[FilterCondition] = Field(default_factory=list)
    time_expressions: List[str] = Field(default_factory=list)
    aggregations: List[str] = Field(default_factory=list)
    sorting: List[SortCondition] = Field(default_factory=list)
    limit: Optional[int] = None
    expected_output: OutputFormat = OutputFormat.TABLE

    # Planning & Multi-step Execution
    requires_multi_step: bool = False
    plan_steps: List[str] = Field(default_factory=list)

    # Observability & Metadata
    confidence: float = 1.0
    understanding_confidence: Optional[UnderstandingConfidence] = None
    source: str = "deterministic"
    business_goal: Optional[str] = None

    @property
    def output_shape(self) -> str:
        return self.expected_output.value if hasattr(self.expected_output, "value") else str(self.expected_output)

    def to_query_understanding(self) -> "QuerySpec":
        """Return self for seamless backward compatibility."""
        return self


# Backward-compatible alias for existing code
QueryUnderstanding = QuerySpec
