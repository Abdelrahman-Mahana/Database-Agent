from typing import Optional
from app.sql_validation.models import ValidationResult

class ValidationCache:
    def __init__(self):
        self._cache = {}
        
    def get(self, query_id: str, policy: str) -> Optional[ValidationResult]:
        return self._cache.get(f"{query_id}:{policy}")
        
    def set(self, query_id: str, policy: str, result: ValidationResult):
        self._cache[f"{query_id}:{policy}"] = result
        
    def clear(self):
        self._cache.clear()
