import structlog
from app.conversation.models import MessageRequest, ConversationContext
from app.conversation.factory import ConversationManagerFactory
from app.conversation.memory_cache import MemoryCache
from app.conversation.metrics import ConversationMetricsCollector
from app.conversation.interfaces import IShortTermMemory, ILongTermMemory

logger = structlog.get_logger(__name__)

class ConversationService:
    def __init__(
        self,
        manager_factory: ConversationManagerFactory,
        cache: MemoryCache,
        metrics: ConversationMetricsCollector,
        stm: IShortTermMemory,
        ltm: ILongTermMemory
    ):
        self.manager_factory = manager_factory
        self.cache = cache
        self.metrics = metrics
        self.stm = stm
        self.ltm = ltm
        self._contexts = {} # Simple memory mock for conversations

    def process_message(self, request: MessageRequest) -> ConversationContext:
        logger.info("Processing conversation message", session_id=request.session_id)
        
        manager = self.manager_factory.get_manager()
        ctx = manager.process_message(request)
        
        self.metrics.log_conversation(ctx)
        self._contexts[ctx.conversation_id] = ctx
        
        return ctx

    def get_conversation(self, conversation_id: str) -> ConversationContext:
        ctx = self._contexts.get(conversation_id)
        if not ctx:
            raise ValueError(f"Conversation {conversation_id} not found.")
        return ctx

    def delete_conversation(self, conversation_id: str) -> None:
        ctx = self._contexts.get(conversation_id)
        if ctx:
            self.stm.clear(ctx.session_id)
            del self._contexts[conversation_id]
            logger.info("Conversation deleted", conversation_id=conversation_id)
