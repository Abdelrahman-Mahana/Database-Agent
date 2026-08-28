"""Models for Schema Grounding Engine."""
from typing import Any, List, Dict, Optional
from pydantic import BaseModel, Field


class Relationship(BaseModel):
    """Represents a foreign key relationship between two schema tables."""
    source_table: str
    source_column: str
    target_table: str
    target_column: str


class GroundedSchema(BaseModel):
    """Compact grounded schema representation containing minimal required tables and join paths."""
    selected_tables: List[str] = Field(default_factory=list)
    selected_columns: Dict[str, List[str]] = Field(default_factory=dict)
    required_relationships: List[Relationship] = Field(default_factory=list)
    schema_text: str = ""
    pruned_table_count: int = 0
    original_table_count: int = 0
    retrieved_seed_tables: List[str] = Field(default_factory=list)
    timings_ms: Dict[str, float] = Field(default_factory=dict)
    fallback_used: bool = False
    is_grounded: bool = True
    unsupported: bool = False
    unsupported_reason: Optional[str] = None
    is_ambiguous: bool = False
    clarification_prompt: Optional[str] = None
    # Auditable provenance for grounding confidence.  A structural fallback is
    # intentionally recorded here, but never treated as relevance evidence.
    evidence: Dict[str, Any] = Field(default_factory=dict)
