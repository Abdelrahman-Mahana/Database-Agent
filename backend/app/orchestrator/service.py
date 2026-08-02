import structlog
from app.orchestrator.models import UserRequest, OrchestratorResponse
from app.orchestrator.factory import OrchestratorFactory
from app.orchestrator.metrics import OrchestratorMetricsCollector

logger = structlog.get_logger(__name__)

class OrchestratorService:
    def __init__(
        self,
        orchestrator_factory: OrchestratorFactory,
        metrics: OrchestratorMetricsCollector
    ):
        self.orchestrator_factory = orchestrator_factory
        self.metrics = metrics

    def process_query(self, request: UserRequest) -> OrchestratorResponse:
        logger.info("OrchestratorService received query", session_id=request.session_id)
        
        orchestrator = self.orchestrator_factory.get_orchestrator()
        response = orchestrator.process(request)
        
        self.metrics.log_response(response)
        
        return response
