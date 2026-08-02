from app.database.discovery.interfaces import IDatabaseInspector
from app.database.discovery.registry import registry

class InspectorFactory:
    """
    Factory to get the appropriate inspector for a given database type.
    """
    @staticmethod
    def create_inspector(engine_name: str) -> IDatabaseInspector:
        inspector_class = registry.get(engine_name)
        if not inspector_class:
            # Fallback to a generic SQLAlchemy inspector if available, else raise
            generic_class = registry.get("generic_sqlalchemy")
            if generic_class:
                return generic_class()
            raise ValueError(f"No inspector found for engine: {engine_name}")
        return inspector_class()
