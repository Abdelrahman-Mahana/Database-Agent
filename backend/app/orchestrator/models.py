from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from enum import Enum
import uuid

class LifecycleState(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    UNDERSTOOD = "UNDERSTOOD"
    PLANNED = "PLANNED"
    EXECUTED = "EXECUTED"
    PROCESSED = "PROCESSED"
    ANALYZED = "ANALYZED"
    CONTEXT_READY = "CONTEXT_READY"
    ANSWER_GENERATED = "ANSWER_GENERATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class DecisionFlags(BaseModel):
    reuse_context: bool = False
    reuse_semantic: bool = False
    refresh_metadata: bool = False
    execute_sql: bool = True
    ask_clarification: bool = False
    skip_discovery: bool = True

class UserRequest(BaseModel):
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    question: str
    force_refresh: bool = False
    context_ttl_valid: bool = False
    schema_version_changed: bool = False
    query_compatible: bool = False
    cache_available: bool = False

class OrchestratorMetrics(BaseModel):
    total_duration_ms: float = 0.0
    stage_durations: Dict[str, float] = Field(default_factory=dict)
    retry_count: int = 0
    reused_stages: List[str] = Field(default_factory=list)

class OrchestratorResponse(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    execution_path: List[str] = Field(default_factory=list)
    pipeline_steps: List[str] = Field(default_factory=list)
    decision_trace: DecisionFlags = Field(default_factory=DecisionFlags)
    reused_components: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    timings: OrchestratorMetrics = Field(default_factory=OrchestratorMetrics)
    final_response: Any = None
    error_message: Optional[str] = None
    state: LifecycleState = LifecycleState.RECEIVED
