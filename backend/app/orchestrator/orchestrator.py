import time
import structlog
from app.orchestrator.interfaces import IOrchestrator, IPipeline, IRetryManager, IFallbackManager, ITimeoutManager
from app.orchestrator.models import UserRequest, OrchestratorResponse, LifecycleState

logger = structlog.get_logger(__name__)

class Orchestrator(IOrchestrator):
    def __init__(
        self,
        pipeline: IPipeline,
        retry_manager: IRetryManager,
        fallback_manager: IFallbackManager,
        timeout_manager: ITimeoutManager
    ):
        self.pipeline = pipeline
        self.retry_manager = retry_manager
        self.fallback_manager = fallback_manager
        self.timeout_manager = timeout_manager

    def process(self, request: UserRequest) -> OrchestratorResponse:
        start_time = time.time()
        response = OrchestratorResponse()
        
        logger.info("Orchestrator starting request", question=request.question)
        
        def run_pipeline():
            self.pipeline.execute(request, response)
            return response
            
        try:
            # Wrap execution with retry and timeout policies
            self.timeout_manager.execute_with_timeout(
                self.retry_manager.execute_with_retry,
                30, # 30 sec total orchestrator timeout
                run_pipeline
            )
        except Exception as e:
            logger.error("Orchestrator failed", error=str(e))
            response.state = LifecycleState.FAILED
            response.final_response = self.fallback_manager.execute_fallback(e, request)
            
        response.timings.total_duration_ms = (time.time() - start_time) * 1000
        return response
