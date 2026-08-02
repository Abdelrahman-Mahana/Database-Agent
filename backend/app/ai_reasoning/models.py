from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import uuid

class ReasoningTrace(BaseModel):
    evidence_used: List[str] = Field(default_factory=list)
    rules_applied: List[str] = Field(default_factory=list)
    confidence_sources: Dict[str, float] = Field(default_factory=dict)

class Citation(BaseModel):
    claim: str = ""
    context_section: str = ""
    relevance_score: float = 1.0

class Recommendation(BaseModel):
    actionable_insight: str = ""
    business_impact: str = ""

class ResponseMetadata(BaseModel):
    provider_used: str = ""
    model_version: str = ""
    tokens_used: int = 0
    processing_time_ms: float = 0.0

class AIResponse(BaseModel):
    response_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    answer: str = ""
    summary: str = ""
    reasoning_trace: ReasoningTrace = Field(default_factory=ReasoningTrace)
    citations: List[Citation] = Field(default_factory=list)
    confidence: float = 1.0
    recommendations: List[Recommendation] = Field(default_factory=list)
    followup_questions: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    response_metadata: ResponseMetadata = Field(default_factory=ResponseMetadata)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class LLMResponse(BaseModel):
    text: str = ""
    raw_response: Any = None
    tokens_used: int = 0
    model: str = ""

class AIReasoningRequest(BaseModel):
    question: str
    context_id: str
    provider: Optional[str] = None
