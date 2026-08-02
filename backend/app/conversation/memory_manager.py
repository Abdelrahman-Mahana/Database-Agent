from app.conversation.interfaces import IMemoryManager, IShortTermMemory, ILongTermMemory, IHistoryCompressor
from app.conversation.models import MemoryContext

class MemoryManager(IMemoryManager):
    def __init__(
        self,
        stm: IShortTermMemory,
        ltm: ILongTermMemory,
        compressor: IHistoryCompressor
    ):
        self.stm = stm
        self.ltm = ltm
        self.compressor = compressor

    def build_memory_context(self, session_id: str) -> MemoryContext:
        raw_history = self.stm.get(session_id)
        compressed = self.compressor.compress(raw_history)
        insights = self.ltm.retrieve(session_id)
        
        ctx = MemoryContext(
            short_term_history=compressed,
            long_term_insights=insights,
            active_entities={} # Extracted in ContextResolver
        )
        # Mock token usage
        ctx.token_usage = len(str(compressed)) // 4
        return ctx
