from app.context_builder.interfaces import IContextExtractor
from app.context_builder.models import StructuredContext, ContextBuildRequest

class ProfilingContextExtractor(IContextExtractor):
    def extract(self, request: ContextBuildRequest, context: StructuredContext) -> None:
        if request.profiling_metadata:
            context.profiling_context.metrics = request.profiling_metadata.get("metrics", {})
