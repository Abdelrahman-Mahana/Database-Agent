from typing import Dict, Optional
from app.dialect.models import DialectQuery

class DialectCache:
    def __init__(self):
        self._cache: Dict[str, DialectQuery] = {}

    def get(self, query_id: str) -> Optional[DialectQuery]:
        return self._cache.get(query_id)
        
    def get_by_logical_id(self, logical_id: str, dialect_name: str) -> Optional[DialectQuery]:
        for dq in self._cache.values():
            if dq.logical_query_id == logical_id and dq.dialect_name == dialect_name:
                return dq
        return None

    def set(self, query: DialectQuery):
        self._cache[query.query_id] = query

    def clear(self):
        self._cache.clear()
