from pydantic import BaseModel, Field
from typing import Dict, Any, List
from datetime import datetime, timezone

class SQLParameter(BaseModel):
    name: str
    value: Any
    type_name: str
    position: int

class SQLDocument(BaseModel):
    query_id: str
    sql: str
    parameters: List[SQLParameter] = Field(default_factory=list)
    dialect: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    estimated_complexity: str = "LOW"
    ast_hash: str = ""
    rendered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    renderer_version: str = "1.0.0"
    formatting_version: str = "1.0.0"
