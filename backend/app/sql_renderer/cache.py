from typing import Dict, Optional
from app.sql_renderer.models import SQLDocument

class SQLCache:
    def __init__(self):
        self._cache: Dict[str, SQLDocument] = {}

    def get(self, query_id: str) -> Optional[SQLDocument]:
        return self._cache.get(query_id)
        
    def get_by_dialect_query(self, query_id: str) -> Optional[SQLDocument]:
        return self._cache.get(query_id) # Using query_id directly for caching

    def set(self, document: SQLDocument):
        self._cache[document.query_id] = document

    def clear(self):
        self._cache.clear()
