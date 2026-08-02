from typing import Dict, Any
from app.orchestrator.interfaces import IRoutingEngine

class RoutingEngine(IRoutingEngine):
    def __init__(self, services: Dict[str, Any]):
        self.services = services

    def route(self, step: str, context: Any) -> Any:
        service = self.services.get(step)
        if not service:
            raise ValueError(f"Service for step {step} not registered in RoutingEngine.")
        return service
