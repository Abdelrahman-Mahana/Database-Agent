from abc import ABC, abstractmethod
from typing import Any, Optional, Protocol
from sqlalchemy.engine import Engine
from app.database.discovery.models import TableMetadata, ColumnMetadata
from app.database.profiling.models import ColumnProfile

class ISamplingProvider(Protocol):
    def build_sample_query(
        self,
        schema_name: str,
        table_name: str,
        select_clause: str,
        strategy: str,
        sample_size: int,
        group_by: Optional[str] = None,
        order_by: Optional[str] = None,
        limit: Optional[int] = None
    ) -> str:
        ...

class ISamplingStrategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

class IColumnProfiler(ABC):
    @abstractmethod
    async def profile(self, engine: Engine, schema_name: str, table_name: str, column: ColumnMetadata, sample_query: str) -> ColumnProfile:
        pass
