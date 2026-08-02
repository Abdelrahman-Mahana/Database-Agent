from app.context_builder.interfaces import IContextExtractor
from app.context_builder.models import StructuredContext, ContextBuildRequest

class SemanticContextExtractor(IContextExtractor):
    def extract(self, request: ContextBuildRequest, context: StructuredContext) -> None:
        if request.semantic_analysis_result:
            context.semantic_context.dataset_profile = request.semantic_analysis_result.get("dataset_profile", {})
            context.semantic_context.relationships = request.semantic_analysis_result.get("relationships", {})
            context.semantic_context.quality_metrics = request.semantic_analysis_result.get("quality_metrics", {})
