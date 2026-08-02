from typing import List
from app.conversation.interfaces import IHistoryCompressor
from app.conversation.models import MemoryEntry

class HistoryCompressor(IHistoryCompressor):
    def compress(self, history: List[MemoryEntry]) -> List[MemoryEntry]:
        if not history:
            return []
            
        # Semantic compression: keep only max 10 turns and preserve analytical meaning
        compressed = []
        for entry in history[-10:]:
            if entry.role in ("user", "assistant"):
                compressed.append(entry)
                
        return compressed
