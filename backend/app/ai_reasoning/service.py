import structlog
from app.context_builder.service import ContextBuilderService
from app.ai_reasoning.models import AIReasoningRequest, AIResponse
from app.ai_reasoning.factory import ReasoningEngineFactory
from app.ai_reasoning.cache import ReasoningCache
from app.ai_reasoning.metrics import ReasoningMetricsCollector

logger = structlog.get_logger(__name__)

class AIReasoningService:
    def __init__(
        self,
        context_service: ContextBuilderService,
        engine_factory: ReasoningEngineFactory,
        cache: ReasoningCache,
        metrics: ReasoningMetricsCollector
    ):
        self.context_service = context_service
        self.engine_factory = engine_factory
        self.cache = cache
        self.metrics = metrics

    def process_reasoning(self, request: AIReasoningRequest) -> AIResponse:
        logger.info("Processing AI reasoning", question=request.question)
        
        # 1. Fetch exact StructuredContext (No DB access here)
        context = self.context_service.get_context(request.context_id)
        
        # 2. Get Engine
        engine = self.engine_factory.get_engine()
        
        # 3. Reason
        response = engine.reason(request, context)
        
        # 4. Cache & Metrics
        self.cache.set(response.response_id, response)
        self.metrics.log_reasoning(response)
        
        return response

    def get_response(self, response_id: str) -> AIResponse:
        resp = self.cache.get(response_id)
        if not resp:
            raise ValueError(f"AIResponse {response_id} not found.")
        return resp
