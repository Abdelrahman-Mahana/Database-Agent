from typing import Dict, Optional
from app.query_understanding.models import QueryUnderstanding

class QueryUnderstandingCache:
    def __init__(self):
        self._cache: Dict[str, QueryUnderstanding] = {}

    def get(self, query_hash: str) -> Optional[QueryUnderstanding]:
        return self._cache.get(query_hash)

    def set(self, query_hash: str, understanding: QueryUnderstanding):
        self._cache[query_hash] = understanding

    def clear(self):
        self._cache.clear()
