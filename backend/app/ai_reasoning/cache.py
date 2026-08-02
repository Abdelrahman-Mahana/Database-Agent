from app.ai_reasoning.models import AIResponse

class ReasoningCache:
    def __init__(self):
        self._cache = {}
        
    def get(self, response_id: str) -> AIResponse:
        return self._cache.get(response_id)
        
    def set(self, response_id: str, response: AIResponse):
        self._cache[response_id] = response
