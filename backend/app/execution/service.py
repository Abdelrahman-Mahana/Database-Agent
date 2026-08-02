import structlog
from app.sql_renderer.service import SQLRenderingService
from app.execution.factory import ExecutorFactory
from app.execution.models import ConnectionConfig, ExecutionResult, ExecutionStatus
from app.execution.cancellation_manager import CancellationManager
from app.execution.cache import ExecutionCache
from app.execution.utils import generate_execution_id
from app.execution.metrics import MetricsCollector

logger = structlog.get_logger(__name__)

class ExecutionService:
    def __init__(
        self,
        executor_factory: ExecutorFactory,
        cancellation_manager: CancellationManager,
        sql_rendering_service: SQLRenderingService,
        cache: ExecutionCache,
        metrics: MetricsCollector
    ):
        self.executor_factory = executor_factory
        self.cancellation_manager = cancellation_manager
        self.sql_rendering_service = sql_rendering_service
        self.cache = cache
        self.metrics = metrics

    def run_query(self, query_id: str, config: ConnectionConfig) -> ExecutionResult:
        logger.info("Executing query", query_id=query_id, dialect=config.dialect)
        
        sql_doc = self.sql_rendering_service.get_document(query_id)
        if not sql_doc:
            raise ValueError(f"SQL Document {query_id} not found.")
            
        execution_id = generate_execution_id()
        executor = self.executor_factory.get_executor(config.dialect)
        
        result = executor.execute(sql_doc, config, execution_id)
        self.cache.set_result(execution_id, result)
        
        self.metrics.record_execution(
            dialect=config.dialect,
            duration=result.duration,
            success=result.status == ExecutionStatus.COMPLETED,
            pool_wait_time=result.pool_wait_time,
            connection_reused=result.connection_reused,
            network_time=result.network_time
        )
        
        return result
        
    def cancel_execution(self, execution_id: str) -> bool:
        logger.info("Cancelling execution", execution_id=execution_id)
        
        result = self.cache.get_result(execution_id)
        if result and result.status in [ExecutionStatus.PENDING, ExecutionStatus.CONNECTING, ExecutionStatus.RUNNING]:
            try:
                result.transition_to(ExecutionStatus.CANCELLING)
            except ValueError:
                pass
            result.cancellation_requested = True
            
        return self.cancellation_manager.cancel(execution_id)
        
    def get_execution_status(self, execution_id: str) -> ExecutionResult:
        result = self.cache.get_result(execution_id)
        if not result:
            raise ValueError(f"Execution {execution_id} not found.")
        return result
