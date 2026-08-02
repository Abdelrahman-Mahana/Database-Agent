class ExecutionCache:
    def __init__(self):
        self._cache = {}
        
    def get_result(self, execution_id: str):
        return self._cache.get(execution_id)
        
    def set_result(self, execution_id: str, result):
        self._cache[execution_id] = result
