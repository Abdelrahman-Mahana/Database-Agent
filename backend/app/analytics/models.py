"""Structured Pydantic models for the Analytics & Insight Engines."""
from enum import Enum
from typing import Any, List, Dict, Optional
from pydantic import BaseModel, Field


class DatasetSummary(BaseModel):
    """Overall dataset metadata and column classifications."""
    row_count: int = 0
    column_count: int = 0
    column_names: List[str] = Field(default_factory=list)
    numeric_columns: List[str] = Field(default_factory=list)
    categorical_columns: List[str] = Field(default_factory=list)
    date_columns: List[str] = Field(default_factory=list)


class NumericSummary(BaseModel):
    """Deterministic statistical summary for a numeric column."""
    column_name: str
    count: int = 0
    null_count: int = 0
    distinct_count: int = 0
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    mean: Optional[float] = None
    median: Optional[float] = None
    stdev: Optional[float] = None


class ValueFrequency(BaseModel):
    """Frequency and percentage metric for a specific categorical value."""
    value: str
    count: int
    percentage: float


class CategoricalSummary(BaseModel):
    """Frequency and distribution summary for a categorical column."""
    column_name: str
    count: int = 0
    null_count: int = 0
    distinct_count: int = 0
    top_values: List[ValueFrequency] = Field(default_factory=list)
    bottom_values: List[ValueFrequency] = Field(default_factory=list)


class AnalyticsResult(BaseModel):
    """Structured output containing all deterministic analytics for a SQL result set."""
    dataset: DatasetSummary
    numeric_stats: Dict[str, NumericSummary] = Field(default_factory=dict)
    categorical_stats: Dict[str, CategoricalSummary] = Field(default_factory=dict)
    execution_time_ms: float = 0.0


# ─── INSIGHT ENGINE MODELS ───


class InsightSeverity(str, Enum):
    """Severity / Priority level for generated deterministic insights."""
    CRITICAL = "critical"   # Empty dataset, massive missing data (>50%)
    WARNING = "warning"     # High cardinality, low variance, missing data (>10%)
    INFO = "info"           # Key statistics, dominant categories, min/max, skew


class InsightItem(BaseModel):
    """Individual deterministic semantic insight item."""
    category: str           # "dataset", "numeric", "categorical"
    severity: InsightSeverity
    title: str              # Short summary title
    message: str            # Concise semantic description
    importance_score: int = 50  # 1-100 priority score for sorting


class InsightResult(BaseModel):
    """Compact semantic output optimized for LLM prompt context injection."""
    summary: str                            # One-line dataset summary
    insights: List[InsightItem] = Field(default_factory=list)  # Sorted prioritized insights
    critical_warnings: List[str] = Field(default_factory=list) # Critical and warning messages
    prompt_context: str = ""                # Compressed token-efficient text for LLM injection
