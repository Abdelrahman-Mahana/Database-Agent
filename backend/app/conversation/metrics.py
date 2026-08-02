import structlog
from app.conversation.models import ConversationContext

logger = structlog.get_logger(__name__)

class ConversationMetricsCollector:
    def log_conversation(self, ctx: ConversationContext):
        logger.info(
            "conversation_metrics",
            conversation_id=ctx.conversation_id,
            session_id=ctx.session_id,
            turn_count=ctx.conversation_state.turn_count,
            resolution_time_ms=ctx.conversation_metrics.resolution_time_ms,
            reused=ctx.reused_context.was_reused,
            valid=ctx.validation.is_valid
        )
