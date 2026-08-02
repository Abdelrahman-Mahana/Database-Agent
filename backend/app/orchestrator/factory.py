from app.orchestrator.interfaces import IOrchestrator

class OrchestratorRegistry:
    def __init__(self):
        self._orchestrators = {}
        
    def register(self, name: str, orchestrator: IOrchestrator):
        self._orchestrators[name] = orchestrator
        
    def get(self, name: str) -> IOrchestrator:
        return self._orchestrators.get(name)

class OrchestratorFactory:
    def __init__(self, registry: OrchestratorRegistry, default_orchestrator: IOrchestrator):
        self.registry = registry
        self.default_orchestrator = default_orchestrator
        
    def get_orchestrator(self, name: str = None) -> IOrchestrator:
        if name:
             o = self.registry.get(name)
             if o: return o
        return self.default_orchestrator
