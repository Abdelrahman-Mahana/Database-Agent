from app.result_processing.models import ProcessedResult

class ResultCache:
    def __init__(self):
        self._cache = {}
        
    def get(self, result_id: str) -> ProcessedResult:
        return self._cache.get(result_id)
        
    def set(self, result_id: str, result: ProcessedResult):
        self._cache[result_id] = result
