from contextlib import contextmanager
from typing import Generator
from app.execution.interfaces import IConnectionManager, ITransactionManager, IConnection
from app.execution.models import ConnectionConfig, TransactionMode

class SessionManager:
    def __init__(self, connection_manager: IConnectionManager, transaction_manager: ITransactionManager):
        self.connection_manager = connection_manager
        self.transaction_manager = transaction_manager
        
    @contextmanager
    def session(self, config: ConnectionConfig, mode: TransactionMode = TransactionMode.READ_ONLY) -> Generator[IConnection, None, None]:
        pool = self.connection_manager.get_pool(config)
        conn = pool.get_connection()
        try:
            self.transaction_manager.begin(conn, mode)
            yield conn
            self.transaction_manager.commit(conn)
        except Exception as e:
            self.transaction_manager.rollback(conn)
            raise e
        finally:
            pool.release_connection(conn)
