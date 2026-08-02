import structlog
from app.context_builder.models import StructuredContext

logger = structlog.get_logger(__name__)

class ContextMetricsCollector:
    def log_context(self, context: StructuredContext):
        logger.info(
            "context_builder_metrics",
            context_id=context.context_id,
            estimated_tokens=context.estimated_tokens,
            compression_ratio=context.compression_ratio,
            confidence=context.confidence,
            warning_count=len(context.warnings)
        )
