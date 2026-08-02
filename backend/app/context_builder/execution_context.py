from app.context_builder.interfaces import IContextExtractor
from app.context_builder.models import StructuredContext, ContextBuildRequest

class ExecutionContextExtractor(IContextExtractor):
    def extract(self, request: ContextBuildRequest, context: StructuredContext) -> None:
        if request.processed_result:
            rows = request.processed_result.get("rows", [])
            context.execution_context.rows_returned = len(rows)
            context.execution_context.schema_def = request.processed_result.get("schema_def", {})
