import structlog
from app.orchestrator.models import OrchestratorResponse

logger = structlog.get_logger(__name__)

class OrchestratorMetricsCollector:
    def log_response(self, response: OrchestratorResponse):
        logger.info(
            "orchestrator_metrics",
            request_id=response.request_id,
            duration_ms=response.timings.total_duration_ms,
            state=response.state.value,
            reused_stages=response.reused_components
        )
