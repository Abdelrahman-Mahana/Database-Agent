from pydantic import BaseModel
from app.execution.models import ExecutionStatus

class ExecutionState(BaseModel):
    execution_id: str
    status: ExecutionStatus
    progress_percentage: float = 0.0
