from abc import ABC, abstractmethod
from typing import Any, Dict
from app.database.discovery.models import DatabaseMetadata

class DatabaseConnector(ABC):
    """
    Abstract interface for all database connectors.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of the connector (e.g., 'postgresql')."""
        pass
        
    @abstractmethod
    async def connect(self, connection_params: Dict[str, Any]) -> None:
        """Establish a connection to the database."""
        pass
        
    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection to the database."""
        pass
        
    @abstractmethod
    async def discover(self) -> DatabaseMetadata:
        """
        Discover database schema, relationships, and basic statistics.
        Must be implemented by the specific database connector.
        """
        pass
        
    @abstractmethod
    def get_engine(self) -> Any:
        """
        Return the SQLAlchemy engine for query execution.
        """
        pass
        
    @abstractmethod
    def build_sample_query(
        self, 
        schema_name: str, 
        table_name: str, 
        select_clause: str,
        strategy: str, 
        sample_size: int,
        group_by: str | None = None,
        order_by: str | None = None,
        limit: int | None = None
    ) -> str:
        """
        Builds the full SELECT query with dialect-specific sampling.
        """
        pass
