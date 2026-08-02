from queue import Queue, Empty
from app.execution.interfaces import IConnectionPool, IConnection
from app.execution.connections import DummyConnection
from app.execution.models import ConnectionConfig

class ConnectionPool(IConnectionPool):
    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._pool: Queue[IConnection] = Queue(maxsize=config.pool_size)
        
        for _ in range(config.pool_size):
            conn = DummyConnection(config.dialect)
            conn.connect()
            self._pool.put(conn)
            
    def get_connection(self) -> IConnection:
        try:
            return self._pool.get(timeout=self.config.timeout_seconds)
        except Empty:
            raise Exception("Connection pool exhausted, timeout while waiting for a connection.")
            
    def release_connection(self, conn: IConnection) -> None:
        self._pool.put(conn)
