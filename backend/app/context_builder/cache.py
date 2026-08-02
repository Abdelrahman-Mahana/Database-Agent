from app.context_builder.models import StructuredContext

class ContextCache:
    def __init__(self):
        self._cache = {}
        
    def get(self, context_id: str) -> StructuredContext:
        return self._cache.get(context_id)
        
    def set(self, context_id: str, context: StructuredContext):
        self._cache[context_id] = context
