from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum
from datetime import datetime, timezone
import uuid

class SemanticClass(str, Enum):
    NUMERIC = "NUMERIC"
    CATEGORICAL = "CATEGORICAL"
    BOOLEAN = "BOOLEAN"
    TEXT = "TEXT"
    TEMPORAL = "TEMPORAL"
    IDENTIFIER = "IDENTIFIER"
    JSON = "JSON"
    ARRAY = "ARRAY"
    BINARY = "BINARY"
    UNKNOWN = "UNKNOWN"

class QualityMetrics(BaseModel):
    null_ratio: float = 0.0
    duplicate_ratio: float = 0.0
    uniqueness_ratio: float = 0.0
    completeness: float = 0.0
    quality_score: float = 0.0

class ColumnProfile(BaseModel):
    name: str
    semantic_class: SemanticClass = SemanticClass.UNKNOWN
    statistics: Dict[str, Any] = Field(default_factory=dict)
    quality: QualityMetrics = Field(default_factory=QualityMetrics)
    outliers: Dict[str, Any] = Field(default_factory=dict)
    distribution: Dict[str, Any] = Field(default_factory=dict)

class DatasetProfile(BaseModel):
    row_count: int = 0
    column_count: int = 0
    total_cells: int = 0
    missing_cells: int = 0
    overall_completeness: float = 0.0

class RelationshipDetection(BaseModel):
    candidate_primary_keys: List[str] = Field(default_factory=list)
    candidate_foreign_keys: Dict[str, List[str]] = Field(default_factory=dict)
    high_correlations: List[Dict[str, Any]] = Field(default_factory=list)
    functional_dependencies: List[Dict[str, Any]] = Field(default_factory=list)

class AnalysisMetrics(BaseModel):
    processing_time_ms: float = 0.0
    peak_memory_mb: float = 0.0

class SemanticAnalysisResult(BaseModel):
    analysis_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    result_id: str
    column_profiles: Dict[str, ColumnProfile] = Field(default_factory=dict)
    dataset_profile: DatasetProfile = Field(default_factory=DatasetProfile)
    relationships: RelationshipDetection = Field(default_factory=RelationshipDetection)
    statistics: Dict[str, Any] = Field(default_factory=dict)
    quality_metrics: Dict[str, Any] = Field(default_factory=dict)
    semantic_metadata: Dict[str, Any] = Field(default_factory=dict)
    analysis_metrics: AnalysisMetrics = Field(default_factory=AnalysisMetrics)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
