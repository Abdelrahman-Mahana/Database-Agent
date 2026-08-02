from app.execution.interfaces import IExecutor
from app.sql_renderer.models import SQLDocument
from app.execution.models import ConnectionConfig, ExecutionResult

class ExecutionRegistry:
    def __init__(self):
        self._executors = {}
        
    def register(self, name: str, executor: IExecutor):
        self._executors[name.upper()] = executor
        
    def get(self, name: str) -> IExecutor:
        return self._executors.get(name.upper())

class ExecutorFactory:
    def __init__(self, registry: ExecutionRegistry, default_executor: IExecutor):
        self.registry = registry
        self.default_executor = default_executor
        
    def get_executor(self, dialect: str) -> IExecutor:
        executor = self.registry.get(dialect)
        if executor:
            return executor
        return self.default_executor
