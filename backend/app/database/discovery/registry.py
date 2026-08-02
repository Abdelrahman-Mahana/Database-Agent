from typing import Dict, Type
from app.database.discovery.interfaces import IDatabaseInspector

class InspectorRegistry:
    """
    Registry for database inspectors.
    """
    def __init__(self):
        self._inspectors: Dict[str, Type[IDatabaseInspector]] = {}

    def register(self, engine_name: str, inspector_class: Type[IDatabaseInspector]):
        self._inspectors[engine_name] = inspector_class

    def get(self, engine_name: str) -> Type[IDatabaseInspector]:
        return self._inspectors.get(engine_name)

# Global registry instance
registry = InspectorRegistry()
