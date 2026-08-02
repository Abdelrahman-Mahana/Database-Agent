import structlog
from app.context_builder.models import ContextBuildRequest, StructuredContext
from app.context_builder.factory import BuilderFactory
from app.context_builder.cache import ContextCache
from app.context_builder.metrics import ContextMetricsCollector

logger = structlog.get_logger(__name__)

class ContextBuilderService:
    def __init__(
        self,
        builder_factory: BuilderFactory,
        cache: ContextCache,
        metrics: ContextMetricsCollector
    ):
        self.builder_factory = builder_factory
        self.cache = cache
        self.metrics = metrics

    def build_context(self, request: ContextBuildRequest) -> StructuredContext:
        logger.info("Building structured context")
        
        builder = self.builder_factory.get_builder()
        context = builder.build(request)
        
        self.cache.set(context.context_id, context)
        self.metrics.log_context(context)
        
        return context

    def get_context(self, context_id: str) -> StructuredContext:
        context = self.cache.get(context_id)
        if not context:
            raise ValueError(f"Context {context_id} not found.")
        return context
