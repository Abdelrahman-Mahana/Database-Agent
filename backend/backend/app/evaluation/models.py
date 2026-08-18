"""Pydantic data models for the AI Evaluation Framework."""
import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class StageLatency(BaseModel):
    """Latency breakdown across pipeline execution stages in milliseconds."""
    intent_classification_ms: float = 0.0
    schema_grounding_ms: float = 0.0
    sql_generation_ms: float = 0.0
    sql_execution_ms: float = 0.0
    analytics_ms: float = 0.0
    insight_ms: float = 0.0
    report_generation_ms: float = 0.0
    chart_suggestion_ms: float = 0.0
    total_ms: float = 0.0


class TokenUsage(BaseModel):
    """LLM token usage statistics and cost estimation."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0


class EvaluationMetrics(BaseModel):
    """Booleans and counters tracking success across all pipeline stages."""
    sql_generation_success: bool = True
    sql_execution_success: bool = True
    repair_attempts: int = 0
    grounding_validation_success: bool = True
    analytics_success: bool = True
    insight_success: bool = True
    report_success: bool = True
    chart_success: bool = True


class EvaluationResult(BaseModel):
    """Structured evaluation output for an agent request."""
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    question: str = ""
    sql_query: str = ""
    metrics: EvaluationMetrics = Field(default_factory=EvaluationMetrics)
    stage_latency: StageLatency = Field(default_factory=StageLatency)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    confidence_score: float = 1.0  # Range 0.0 to 1.0
    quality_score: float = 100.0   # Range 0.0 to 100.0
    summary: str = ""
