import time
from app.conversation.interfaces import (
    IConversationManager, ISessionManager, IMemoryManager, IContextResolver,
    IConversationValidator, IShortTermMemory, ILongTermMemory, ITTLManager
)
from app.conversation.models import MessageRequest, ConversationContext, ConversationStateEnum, MemoryEntry

class ConversationManager(IConversationManager):
    def __init__(
        self,
        session_manager: ISessionManager,
        memory_manager: IMemoryManager,
        context_resolver: IContextResolver,
        validator: IConversationValidator,
        stm: IShortTermMemory,
        ltm: ILongTermMemory,
        ttl_manager: ITTLManager
    ):
        self.session_manager = session_manager
        self.memory_manager = memory_manager
        self.context_resolver = context_resolver
        self.validator = validator
        self.stm = stm
        self.ltm = ltm
        self.ttl_manager = ttl_manager

    def process_message(self, request: MessageRequest) -> ConversationContext:
        start_time = time.time()
        
        session_id = self.session_manager.get_or_create_session(request.session_id)
        request.session_id = session_id
        
        memory_context = self.memory_manager.build_memory_context(session_id)
        
        ctx = self.context_resolver.resolve(request, memory_context)
        
        validation_result = self.validator.validate(ctx)
        ctx.validation = validation_result
        
        # State machine transition
        try:
            ctx.conversation_state.transition_to(ConversationStateEnum.ACTIVE)
        except ValueError as e:
            ctx.conversation_state.state = ConversationStateEnum.ACTIVE # force initialize if failed
            
        ctx.conversation_state.turn_count += 1
        
        # Memory storage via strictly typed MemoryEntry
        entry = MemoryEntry(
            role="user",
            question=ctx.resolved_question,
            entities=ctx.resolved_entities,
            context_id=ctx.reused_context.source_context_id or request.context_id
        )
        self.stm.add(session_id, entry)
        
        ctx.conversation_metrics.resolution_time_ms = (time.time() - start_time) * 1000
        ctx.conversation_metrics.entities_resolved = len(ctx.resolved_entities)
        ctx.conversation_metrics.references_resolved = len(ctx.resolved_references)
        ctx.conversation_metrics.context_reused = ctx.reused_context.was_reused
        
        return ctx
