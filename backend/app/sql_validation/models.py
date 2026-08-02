from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
from datetime import datetime, timezone

import os

class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
    
    @property
    def weight(self) -> int:
        weights = {
            "INFO": 1,
            "WARNING": 2,
            "ERROR": 3,
            "CRITICAL": 4
        }
        return weights.get(self.value, 0)
        
    def __lt__(self, other):
        if not isinstance(other, Severity):
            return NotImplemented
        return self.weight < other.weight

class Violation(BaseModel):
    rule: str
    code: str
    message: str
    reason: str
    suggested_fix: str
    severity: Severity

class ValidationResult(BaseModel):
    allowed: bool
    severity: Optional[Severity] = None
    violations: List[Violation] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    confidence: float = 1.0
    policy_used: str
    validation_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    validator_version: str = Field(default_factory=lambda: os.environ.get("APP_VERSION", "1.0.0"))

class ValidationContext(BaseModel):
    policy: str
    query_id: str
