from typing import List
from app.conversation.interfaces import ILongTermMemory
from app.conversation.models import MemoryEntry

class LongTermMemory(ILongTermMemory):
    def __init__(self, memory_cache):
        self.memory_cache = memory_cache

    def store_insight(self, session_id: str, insight: MemoryEntry) -> None:
        key = f"ltm:{session_id}"
        insights = self.memory_cache.get(key) or []
        insight_dict = insight.model_dump()
        if insight_dict not in insights:
            insights.append(insight_dict)
            self.memory_cache.set(key, insights)

    def retrieve(self, session_id: str) -> List[MemoryEntry]:
        key = f"ltm:{session_id}"
        data = self.memory_cache.get(key) or []
        return [MemoryEntry(**e) for e in data]
