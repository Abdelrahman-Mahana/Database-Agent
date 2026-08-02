from app.ai_reasoning.interfaces import IReasoningEngine

class ReasoningEngineRegistry:
    def __init__(self):
        self._engines = {}
        
    def register(self, name: str, engine: IReasoningEngine):
        self._engines[name.upper()] = engine
        
    def get(self, name: str) -> IReasoningEngine:
        return self._engines.get(name.upper())

class ReasoningEngineFactory:
    def __init__(self, registry: ReasoningEngineRegistry, default_engine: IReasoningEngine):
        self.registry = registry
        self.default_engine = default_engine
        
    def get_engine(self, domain: str = None) -> IReasoningEngine:
        if domain:
            b = self.registry.get(domain)
            if b: return b
        return self.default_engine
