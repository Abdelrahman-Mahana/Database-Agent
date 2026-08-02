from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from uuid import uuid4
from datetime import datetime, timezone

class StepType(str, Enum):
    SCAN_TABLE = "SCAN_TABLE"
    JOIN = "JOIN"
    FILTER = "FILTER"
    GROUP_BY = "GROUP_BY"
    AGGREGATE = "AGGREGATE"
    SORT = "SORT"
    LIMIT = "LIMIT"
    UNION = "UNION"
    DISTINCT = "DISTINCT"
    PROJECT = "PROJECT"
    CALCULATE = "CALCULATE"

class AggregationFunction(str, Enum):
    SUM = "SUM"
    AVG = "AVG"
    COUNT = "COUNT"
    MIN = "MIN"
    MAX = "MAX"
    MEDIAN = "MEDIAN"
    STDDEV = "STDDEV"
    VARIANCE = "VARIANCE"

class SortDirection(str, Enum):
    ASC = "ASC"
    DESC = "DESC"

class DependencyType(str, Enum):
    DATA = "DATA"
    CONTROL = "CONTROL"
    RESOURCE = "RESOURCE"

class ExecutionStep(BaseModel):
    step_id: str = Field(default_factory=lambda: str(uuid4()))
    step_type: StepType
    parameters: Dict[str, Any] = Field(default_factory=dict)
    inputs: List[str] = Field(default_factory=list) # IDs of parent steps
    outputs: List[str] = Field(default_factory=list) # Conceptual output names
    confidence: float = 1.0
    decision_reason: Optional[str] = None
    evidence: List[str] = Field(default_factory=list)

class ExecutionDependency(BaseModel):
    source_step_id: str
    target_step_id: str
    dependency_type: DependencyType = DependencyType.DATA

class ExecutionGraph(BaseModel):
    steps: List[ExecutionStep] = Field(default_factory=list)
    dependencies: List[ExecutionDependency] = Field(default_factory=list)

class PlanStatistics(BaseModel):
    estimated_complexity: str = "LOW"
    estimated_cost: float = 0.0
    estimated_rows: int = 0
    estimated_memory: Optional[int] = None
    estimated_duration: Optional[float] = None

class ExecutionPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    query_hash: str
    schema_hash: str = ""
    planner_version: str = "1.0.0"
    graph: ExecutionGraph
    statistics: PlanStatistics
    confidence: float
