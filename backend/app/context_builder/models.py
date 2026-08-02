from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import uuid

class QuestionContext(BaseModel):
    parsed_question: Dict[str, Any] = Field(default_factory=dict)
    business_terms: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)

class DatabaseContext(BaseModel):
    dialect: str = ""
    version: str = ""

class ColumnContext(BaseModel):
    name: str = ""
    type: str = ""
    description: str = ""
    relevance_score: float = 0.0

class TableContext(BaseModel):
    name: str = ""
    description: str = ""
    columns: Dict[str, ColumnContext] = Field(default_factory=dict)
    relevance_score: float = 0.0

class SchemaContext(BaseModel):
    tables: Dict[str, TableContext] = Field(default_factory=dict)
    summary: str = ""

class SemanticContext(BaseModel):
    dataset_profile: Dict[str, Any] = Field(default_factory=dict)
    relationships: Dict[str, Any] = Field(default_factory=dict)
    quality_metrics: Dict[str, Any] = Field(default_factory=dict)

class ProfilingContext(BaseModel):
    metrics: Dict[str, Any] = Field(default_factory=dict)

class PlanningContext(BaseModel):
    nodes: List[Dict[str, Any]] = Field(default_factory=list)
    estimated_cost: float = 0.0
    logical_intent: str = ""

class ExecutionContext(BaseModel):
    rows_returned: int = 0
    schema_def: Dict[str, Any] = Field(default_factory=dict)

class StructuredContext(BaseModel):
    context_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    question_context: QuestionContext = Field(default_factory=QuestionContext)
    database_context: DatabaseContext = Field(default_factory=DatabaseContext)
    schema_context: SchemaContext = Field(default_factory=SchemaContext)
    semantic_context: SemanticContext = Field(default_factory=SemanticContext)
    profiling_context: ProfilingContext = Field(default_factory=ProfilingContext)
    planning_context: PlanningContext = Field(default_factory=PlanningContext)
    execution_context: ExecutionContext = Field(default_factory=ExecutionContext)
    
    relevant_entities: List[str] = Field(default_factory=list)
    business_terms: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    confidence: float = 1.0
    estimated_tokens: int = 0
    compression_ratio: float = 1.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ContextBuildRequest(BaseModel):
    # Using generic dicts for upstream components that may have varied schemas
    # to maintain decoupled solid architecture.
    database_metadata: Optional[Dict[str, Any]] = None
    schema_intelligence: Optional[Dict[str, Any]] = None
    profiling_metadata: Optional[Dict[str, Any]] = None
    query_understanding: Optional[Dict[str, Any]] = None
    execution_plan: Optional[Dict[str, Any]] = None
    logical_query: Optional[Dict[str, Any]] = None
    semantic_analysis_result: Optional[Dict[str, Any]] = None
    processed_result: Optional[Dict[str, Any]] = None
    
class ValidationResult(BaseModel):
    is_valid: bool = True
    missing_context: List[str] = Field(default_factory=list)
    duplicated_context: List[str] = Field(default_factory=list)
    conflicting_metadata: List[str] = Field(default_factory=list)

class OptimizationMetrics(BaseModel):
    original_size_bytes: int = 0
    compressed_size_bytes: int = 0
    compression_ratio: float = 1.0
