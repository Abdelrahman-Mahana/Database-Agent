import structlog
from app.ai_reasoning.models import AIResponse

logger = structlog.get_logger(__name__)

class ReasoningMetricsCollector:
    def log_reasoning(self, response: AIResponse):
        logger.info(
            "ai_reasoning_metrics",
            response_id=response.response_id,
            confidence=response.confidence,
            provider=response.response_metadata.provider_used,
            tokens_used=response.response_metadata.tokens_used,
            processing_time_ms=response.response_metadata.processing_time_ms
        )
