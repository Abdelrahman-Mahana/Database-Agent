from app.conversation.interfaces import IContextReuse, ITTLManager
from app.conversation.models import MessageRequest, MemoryContext, ContextReuseDecision

class ContextReuse(IContextReuse):
    def evaluate_reuse(self, request: MessageRequest, memory: MemoryContext, ttl_manager: ITTLManager) -> ContextReuseDecision:
        if request.context_id and request.structured_context:
            if ttl_manager.is_context_valid(request.structured_context.created_at):
                return ContextReuseDecision.REUSE_CONTEXT
            else:
                return ContextReuseDecision.REBUILD_CONTEXT
                
        if memory.short_term_history:
            last_entry = memory.short_term_history[-1]
            if last_entry.context_id:
                # Naive check: if question is short, probably a follow up on same context
                if len(request.question.split()) < 7:
                    return ContextReuseDecision.REUSE_CONTEXT
                else:
                    return ContextReuseDecision.REEXECUTE_SQL
                    
        return ContextReuseDecision.NONE
