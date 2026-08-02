from typing import Dict, Optional
from app.logical_query.models import LogicalQuery

class LogicalQueryCache:
    def __init__(self):
        self._cache: Dict[str, LogicalQuery] = {}

    def get(self, query_id: str) -> Optional[LogicalQuery]:
        return self._cache.get(query_id)
        
    def get_by_plan_id(self, plan_id: str) -> Optional[LogicalQuery]:
        # Weak back-reference via query_hash mapping in real life, mock approach here
        pass

    def set(self, query: LogicalQuery):
        self._cache[query.query_id] = query

    def clear(self):
        self._cache.clear()
