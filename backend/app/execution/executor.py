from datetime import datetime, timezone
import time
from app.sql_renderer.models import SQLDocument
from app.execution.interfaces import IExecutor
from app.execution.models import ExecutionResult, ExecutionStatus, ConnectionConfig, TransactionMode
from app.execution.session_manager import SessionManager
from app.execution.cancellation_manager import CancellationManager
from app.execution.retry_manager import RetryManager
from app.execution.timeout_manager import TimeoutManager, TimeoutError

class DeterministicExecutor(IExecutor):
    def __init__(
        self, 
        session_manager: SessionManager, 
        cancellation_manager: CancellationManager,
        retry_manager: RetryManager,
        timeout_manager: TimeoutManager
    ):
        self.session_manager = session_manager
        self.cancellation_manager = cancellation_manager
        self.retry_manager = retry_manager
        self.timeout_manager = timeout_manager

    def execute(self, sql_doc: SQLDocument, config: ConnectionConfig, execution_id: str) -> ExecutionResult:
        start_time = time.time()
        result = ExecutionResult(execution_id=execution_id, status=ExecutionStatus.PENDING)
        
        try:
            result.transition_to(ExecutionStatus.CONNECTING)
            
            pool_start = time.time()
            with self.session_manager.session(config, mode=TransactionMode.READ_ONLY) as conn:
                pool_wait = time.time() - pool_start
                result.pool_wait_time = pool_wait
                
                connection_time = time.time() - start_time - pool_wait
                result.connection_time = connection_time
                result.connection_reused = getattr(conn, 'is_reused', True)
                
                self.cancellation_manager.register(execution_id, driver_hook=conn.cancel_current_execution)
                
                result.transition_to(ExecutionStatus.RUNNING)
                
                def _execute_logic():
                    if self.cancellation_manager.is_cancelled(execution_id):
                        raise Exception("Execution was cancelled by user.")
                    
                    with self.timeout_manager.enforce_timeout(config.timeout_seconds):
                        if self.cancellation_manager.is_cancelled(execution_id):
                            raise Exception("Execution was cancelled by user.")
                            
                        return conn.execute(sql_doc)
                        
                db_result, retries = self.retry_manager.execute_with_retry_tracked(_execute_logic)
                result.retry_count = retries
                
                result.transition_to(ExecutionStatus.COMPLETED)
                result.rows_returned = db_result.get("rows_returned", 0)
                result.rows_affected = db_result.get("rows_affected", 0)
                result.database_metadata = db_result.get("metadata", {})
                
        except TimeoutError as e:
            if result.status == ExecutionStatus.CANCELLING:
                result.transition_to(ExecutionStatus.CANCELLED)
                result.cancellation_requested = True
            else:
                result.transition_to(ExecutionStatus.TIMEOUT)
                result.timeout_triggered = True
            result.error_message = str(e)
        except Exception as e:
            if str(e) == "Execution was cancelled by user." or self.cancellation_manager.is_cancelled(execution_id):
                result.transition_to(ExecutionStatus.CANCELLED)
                result.cancellation_requested = True
            else:
                result.transition_to(ExecutionStatus.FAILED)
            result.error_message = str(e)
        finally:
            result.duration = time.time() - start_time
            result.completed_at = datetime.now(timezone.utc)
            self.cancellation_manager.unregister(execution_id)
            
        return result
