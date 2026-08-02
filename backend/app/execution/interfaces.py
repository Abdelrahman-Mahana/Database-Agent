from abc import ABC, abstractmethod
from typing import Any, Dict, Callable
from app.sql_renderer.models import SQLDocument
from app.execution.models import ExecutionResult, TransactionMode, ConnectionConfig

class ICancellationManager(ABC):
    @abstractmethod
    def register(self, execution_id: str, driver_hook: Callable[[], bool] = None) -> None:
        pass
        
    @abstractmethod
    def cancel(self, execution_id: str) -> bool:
        pass
        
    @abstractmethod
    def is_cancelled(self, execution_id: str) -> bool:
        pass

class IConnection(ABC):
    @abstractmethod
    def connect(self) -> None:
        pass
        
    @abstractmethod
    def close(self) -> None:
        pass
        
    @abstractmethod
    def begin(self, mode: TransactionMode) -> None:
        pass
        
    @abstractmethod
    def commit(self) -> None:
        pass
        
    @abstractmethod
    def rollback(self) -> None:
        pass
        
    @abstractmethod
    def execute(self, sql_doc: SQLDocument) -> Dict[str, Any]:
        pass
        
    @abstractmethod
    def cancel_current_execution(self) -> bool:
        pass

class IConnectionPool(ABC):
    @abstractmethod
    def get_connection(self) -> IConnection:
        pass
        
    @abstractmethod
    def release_connection(self, conn: IConnection) -> None:
        pass

class IConnectionManager(ABC):
    @abstractmethod
    def get_pool(self, config: ConnectionConfig) -> IConnectionPool:
        pass

class ITransactionManager(ABC):
    @abstractmethod
    def begin(self, conn: IConnection, mode: TransactionMode) -> None:
        pass
        
    @abstractmethod
    def commit(self, conn: IConnection) -> None:
        pass
        
    @abstractmethod
    def rollback(self, conn: IConnection) -> None:
        pass

class IExecutor(ABC):
    @abstractmethod
    def execute(self, sql_doc: SQLDocument, config: ConnectionConfig, execution_id: str) -> ExecutionResult:
        pass
