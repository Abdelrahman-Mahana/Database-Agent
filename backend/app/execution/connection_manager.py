from typing import Dict
from app.execution.interfaces import IConnectionManager, IConnectionPool
from app.execution.connection_pool import ConnectionPool
from app.execution.models import ConnectionConfig

class ConnectionManager(IConnectionManager):
    def __init__(self):
        self._pools: Dict[str, IConnectionPool] = {}
        
    def _get_pool_key(self, config: ConnectionConfig) -> str:
        return f"{config.dialect}://{config.user}@{config.host}:{config.port}/{config.database}"
        
    def get_pool(self, config: ConnectionConfig) -> IConnectionPool:
        key = self._get_pool_key(config)
        if key not in self._pools:
            self._pools[key] = ConnectionPool(config)
        return self._pools[key]
