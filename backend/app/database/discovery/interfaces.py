from abc import ABC, abstractmethod
from typing import Any
from app.database.discovery.models import DatabaseMetadata

class IDatabaseInspector(ABC):
    """
    Abstract interface for database inspectors.
    """
    
    @abstractmethod
    def inspect(self, engine_or_connection: Any, db_name: str) -> DatabaseMetadata:
        """
        Inspects the database and returns a complete DatabaseMetadata graph.
        """
        pass
