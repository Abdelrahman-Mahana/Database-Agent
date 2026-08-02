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


class QueryUnderstanding(BaseModel):
    """Structured, deterministic semantic representation of a user query."""
    raw_question: str
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

    # --- Phase 1 (LLM Understanding Layer) additions ---
    # True when the question itself (not a keyword like "compare"/"trend")
    # genuinely needs decomposition into sub-questions. Set by the LLM
    # understanding node's own reasoning; the regex parser never sets this
    # (it has no notion of "requires planning" beyond analysis_type keywords),
    # so it defaults to False and callers fall back to
    # `analysis_type in COMPLEX_ANALYSIS_TYPES` in that case.
    requires_multi_step: bool = False
    # How confident the understanding is in its own output. The regex parser
    # is always "confident" (1.0) because it's deterministic pattern matching,
    # not judgment. The LLM path reports its own uncertainty so the caller can
    # fall back to the deterministic parser when it's below threshold.
    confidence: float = 1.0
    # Which layer actually produced this understanding: "regex" (deterministic
    # parser), "llm" (LLM reasoning node), or "llm_fallback_regex" (LLM path
    # was enabled but failed/low-confidence, so this is the regex result).
    # Purely for observability/eval - never changes downstream behavior.
    source: str = "regex"
    business_goal: Optional[str] = None
