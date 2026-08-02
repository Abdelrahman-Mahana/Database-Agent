from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
from enum import Enum
from datetime import datetime, timezone
import uuid

class ExecutionStatus(str, Enum):
    PENDING = "PENDING"
    CONNECTING = "CONNECTING"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"

VALID_TRANSITIONS = {
    ExecutionStatus.PENDING: {ExecutionStatus.CONNECTING, ExecutionStatus.CANCELLING, ExecutionStatus.FAILED},
    ExecutionStatus.CONNECTING: {ExecutionStatus.RUNNING, ExecutionStatus.CANCELLING, ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT},
    ExecutionStatus.RUNNING: {ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLING, ExecutionStatus.TIMEOUT},
    ExecutionStatus.CANCELLING: {ExecutionStatus.CANCELLED, ExecutionStatus.FAILED},
    ExecutionStatus.COMPLETED: set(),
    ExecutionStatus.FAILED: set(),
    ExecutionStatus.CANCELLED: set(),
    ExecutionStatus.TIMEOUT: set(),
}

def is_valid_transition(current: ExecutionStatus, next_state: ExecutionStatus) -> bool:
    return next_state in VALID_TRANSITIONS.get(current, set())

class TransactionMode(str, Enum):
    READ_ONLY = "READ_ONLY"
    READ_WRITE = "READ_WRITE"
    AUTOCOMMIT = "AUTOCOMMIT"

class ExecutionResult(BaseModel):
    execution_id: str
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: ExecutionStatus
    duration: float = 0.0
    connection_time: float = 0.0
    pool_wait_time: float = 0.0
    network_time: float = 0.0
    connection_reused: bool = False
    rows_returned: int = 0
    rows_affected: int = 0
    retry_count: int = 0
    timeout_triggered: bool = False
    cancellation_requested: bool = False
    database_metadata: Dict[str, Any] = Field(default_factory=dict)
    execution_metadata: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    
    def transition_to(self, new_status: ExecutionStatus):
        if not is_valid_transition(self.status, new_status):
            raise ValueError(f"Invalid state transition from {self.status} to {new_status}")
        self.status = new_status

class ConnectionConfig(BaseModel):
    dialect: str
    host: str
    port: int
    database: str
    user: str
    password: str
    pool_size: int
    timeout_seconds: int
