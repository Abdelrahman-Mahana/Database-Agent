from typing import List
from app.conversation.interfaces import IShortTermMemory
from app.conversation.models import MemoryEntry

class ShortTermMemory(IShortTermMemory):
    def __init__(self, memory_cache):
        self.memory_cache = memory_cache

    def add(self, session_id: str, entry: MemoryEntry) -> None:
        key = f"stm:{session_id}"
        history = self.memory_cache.get(key) or []
        history.append(entry.model_dump())
        self.memory_cache.set(key, history)

    def get(self, session_id: str) -> List[MemoryEntry]:
        key = f"stm:{session_id}"
        data = self.memory_cache.get(key) or []
        return [MemoryEntry(**e) for e in data]

    def clear(self, session_id: str) -> None:
        key = f"stm:{session_id}"
        self.memory_cache.delete(key)
