"""Structured data models for the SQL processing package."""
from typing import Any, List, Optional
from pydantic import BaseModel, Field


class ValidationResult(BaseModel):
    """Result of SQL safety or syntax validation."""
    valid: bool
    reason: Optional[str] = None
    query_type: Optional[str] = None


class GroundingResult(BaseModel):
    """Result of semantic schema grounding validation."""
    grounded: bool
    missing_entities: List[str] = Field(default_factory=list)
    missing_columns: List[str] = Field(default_factory=list)
    unanswerable_reason: Optional[str] = None


class ExecutionRepairResult(BaseModel):
    """Output payload from SQL execution and repair loop."""
    rows: List[dict] = Field(default_factory=list)
    final_sql: str
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    suggestions: List[str] = Field(default_factory=list)
