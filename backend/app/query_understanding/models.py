from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime

class QueryIntent(str, Enum):
    SELECT = "SELECT"
    COMPARE = "COMPARE"
    TREND = "TREND"
    AGGREGATION = "AGGREGATION"
    EXPLAIN = "EXPLAIN"
    DESCRIBE = "DESCRIBE"
    SUMMARY = "SUMMARY"
    COUNT = "COUNT"
    TOP_K = "TOP_K"
    BOTTOM_K = "BOTTOM_K"
    UNKNOWN = "UNKNOWN"

class FilterOperator(str, Enum):
    EQUALS = "EQUALS"
    CONTAINS = "CONTAINS"
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    BETWEEN = "BETWEEN"
    IN = "IN"
    NOT_IN = "NOT_IN"

class QueryFilter(BaseModel):
    field: str
    operator: FilterOperator
    value: Any

class TimeRange(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    expression: str

class QueryEntities(BaseModel):
    tables: List[str] = Field(default_factory=list)
    columns: List[str] = Field(default_factory=list)
    metrics: List[str] = Field(default_factory=list)
    dimensions: List[str] = Field(default_factory=list)
    business_terms: List[str] = Field(default_factory=list)
    time_expressions: List[str] = Field(default_factory=list)

class QueryAmbiguity(BaseModel):
    issue_type: str
    description: str
    candidates: List[str] = Field(default_factory=list)

class QueryContext(BaseModel):
    tables: List[Dict[str, Any]] = Field(default_factory=list)
    columns: List[Dict[str, Any]] = Field(default_factory=list)
    relationships: List[Dict[str, Any]] = Field(default_factory=list)
    statistics: List[Dict[str, Any]] = Field(default_factory=list)

class QueryRouting(str, Enum):
    DATABASE_QUERY = "DATABASE_QUERY"
    GENERAL_KNOWLEDGE = "GENERAL_KNOWLEDGE"
    HYBRID = "HYBRID"

class ConfidenceScore(BaseModel):
    score: float
    evidence: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)

class QueryUnderstanding(BaseModel):
    original_query: str
    normalized_query: str
    intent: QueryIntent
    entities: QueryEntities
    metrics: List[str] = Field(default_factory=list)
    dimensions: List[str] = Field(default_factory=list)
    filters: List[QueryFilter] = Field(default_factory=list)
    time_range: Optional[TimeRange] = None
    ambiguities: List[QueryAmbiguity] = Field(default_factory=list)
    context: QueryContext
    routing: QueryRouting
    confidence: ConfidenceScore
