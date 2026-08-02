from pydantic import BaseModel
from typing import Dict, Any

class ExecutionContext(BaseModel):
    user_id: str
    roles: list[str]
    client_ip: str
    request_id: str
