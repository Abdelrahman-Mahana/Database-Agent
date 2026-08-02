from app.conversation.interfaces import IContextResolver
from app.conversation.models import ConversationContext, MessageRequest, MemoryContext

class ContextResolver(IContextResolver):
    def __init__(self, entity_tracker, reference_resolver, intent_resolver, context_reuse, ttl_manager):
        self.entity_tracker = entity_tracker
        self.reference_resolver = reference_resolver
        self.intent_resolver = intent_resolver
        self.context_reuse = context_reuse
        self.ttl_manager = ttl_manager

    def resolve(self, request: MessageRequest, memory: MemoryContext) -> ConversationContext:
        ctx = ConversationContext()
        ctx.session_id = request.session_id or ctx.session_id
        ctx.conversation_id = request.conversation_id or ctx.conversation_id
        
        ctx.resolved_entities = self.entity_tracker.track(ctx.session_id, request.question, request.structured_context)
        
        ctx.resolved_references = self.reference_resolver.resolve(request.question, ctx.resolved_entities, memory)
        
        ctx.resolved_question = self.intent_resolver.resolve(request.question, ctx.resolved_references)
        
        decision = self.context_reuse.evaluate_reuse(request, memory, self.ttl_manager)
        
        if decision == "REUSE_CONTEXT":
            ctx.reused_context.was_reused = True
            ctx.reused_context.source_context_id = request.context_id or (memory.short_term_history[-1].context_id if memory.short_term_history else None)
        
        ctx.reused_context.decision = decision
            
        ctx.memory_context = memory
        return ctx
