from app.semantic_analysis.analyzer import SemanticAnalyzer

class AnalyzerRegistry:
    def __init__(self):
        self._analyzers = {}
        
    def register(self, name: str, analyzer: SemanticAnalyzer):
        self._analyzers[name.upper()] = analyzer
        
    def get(self, name: str) -> SemanticAnalyzer:
        return self._analyzers.get(name.upper())

class AnalyzerFactory:
    def __init__(self, registry: AnalyzerRegistry, default_analyzer: SemanticAnalyzer):
        self.registry = registry
        self.default_analyzer = default_analyzer
        
    def get_analyzer(self, domain: str = None) -> SemanticAnalyzer:
        if domain:
            analyzer = self.registry.get(domain)
            if analyzer:
                return analyzer
        return self.default_analyzer
