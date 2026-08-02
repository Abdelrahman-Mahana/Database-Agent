from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import uuid
from enum import Enum

from app.context_builder.models import StructuredContext

class ConversationStateEnum(str, Enum):
    INITIALIZED = "INITIALIZED"
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"

class TrackedTable(BaseModel):
    name: str
    schema_name: Optional[str] = None
    
class TrackedMetric(BaseModel):
    name: str
    value: Optional[float] = None
    
class TrackedFilter(BaseModel):
    column: str
    operator: str
    value: Any
    
class TrackedResult(BaseModel):
    row_count: int
    has_aggregations: bool

class TrackedEntity(BaseModel):
    entity_type: str
    name: str
    table: Optional[TrackedTable] = None
    metric: Optional[TrackedMetric] = None
    filter_data: Optional[TrackedFilter] = None
    result: Optional[TrackedResult] = None
    confidence: float = 1.0

class MemoryEntry(BaseModel):
    role: str
    question: str
    entities: List[TrackedEntity] = Field(default_factory=list)
    context_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ConversationMetrics(BaseModel):
    resolution_time_ms: float = 0.0
    history_compression_ratio: float = 1.0
    entities_resolved: int = 0
    references_resolved: int = 0
    context_reused: bool = False

class MemoryContext(BaseModel):
    short_term_history: List[MemoryEntry] = Field(default_factory=list)
    long_term_insights: List[MemoryEntry] = Field(default_factory=list)
    active_entities: Dict[str, TrackedEntity] = Field(default_factory=dict)
    token_usage: int = 0

class ConversationState(BaseModel):
    state: ConversationStateEnum = ConversationStateEnum.INITIALIZED
    last_active_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    turn_count: int = 0
    
    def transition_to(self, new_state: ConversationStateEnum):
        valid_transitions = {
            ConversationStateEnum.INITIALIZED: [ConversationStateEnum.ACTIVE, ConversationStateEnum.TERMINATED],
            ConversationStateEnum.ACTIVE: [ConversationStateEnum.IDLE, ConversationStateEnum.TERMINATED, ConversationStateEnum.ACTIVE],
            ConversationStateEnum.IDLE: [ConversationStateEnum.ACTIVE, ConversationStateEnum.EXPIRED, ConversationStateEnum.TERMINATED],
            ConversationStateEnum.EXPIRED: [ConversationStateEnum.INITIALIZED, ConversationStateEnum.TERMINATED],
            ConversationStateEnum.TERMINATED: []
        }
        if new_state in valid_transitions[self.state]:
            self.state = new_state
            self.last_active_at = datetime.now(timezone.utc)
        else:
            raise ValueError(f"Invalid state transition from {self.state} to {new_state}")

class ReusedContext(BaseModel):
    was_reused: bool = False
    source_context_id: Optional[str] = None
    reused_entities: List[str] = Field(default_factory=list)

class ValidationResult(BaseModel):
    is_valid: bool = True
    ambiguous_references: List[str] = Field(default_factory=list)
    missing_entities: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

class ContextReuseDecision(str, Enum):
    REUSE_CONTEXT = "REUSE_CONTEXT"
    REBUILD_CONTEXT = "REBUILD_CONTEXT"
    REEXECUTE_SQL = "REEXECUTE_SQL"
    NONE = "NONE"

class ReusedContext(BaseModel):
    was_reused: bool = False
    decision: ContextReuseDecision = ContextReuseDecision.NONE
    source_context_id: Optional[str] = None
    reused_entities: List[TrackedEntity] = Field(default_factory=list)

class ConversationContext(BaseModel):
    conversation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    resolved_question: str = ""
    resolved_entities: List[TrackedEntity] = Field(default_factory=list)
    resolved_references: Dict[str, TrackedEntity] = Field(default_factory=dict)
    conversation_state: ConversationState = Field(default_factory=ConversationState)
    memory_context: MemoryContext = Field(default_factory=MemoryContext)
    reused_context: ReusedContext = Field(default_factory=ReusedContext)
    conversation_metrics: ConversationMetrics = Field(default_factory=ConversationMetrics)
    validation: ValidationResult = Field(default_factory=ValidationResult)

class MessageRequest(BaseModel):
    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    question: str
    context_id: Optional[str] = None
    structured_context: Optional[StructuredContext] = None
