from app.semantic_analysis.models import SemanticAnalysisResult

class SemanticCache:
    def __init__(self):
        self._cache = {}
        
    def get(self, analysis_id: str) -> SemanticAnalysisResult:
        return self._cache.get(analysis_id)
        
    def set(self, analysis_id: str, result: SemanticAnalysisResult):
        self._cache[analysis_id] = result
