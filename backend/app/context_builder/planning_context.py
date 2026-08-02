from app.context_builder.interfaces import IContextExtractor
from app.context_builder.models import StructuredContext, ContextBuildRequest

class PlanningContextExtractor(IContextExtractor):
    def extract(self, request: ContextBuildRequest, context: StructuredContext) -> None:
        if request.execution_plan:
            context.planning_context.nodes = request.execution_plan.get("nodes", [])
            context.planning_context.estimated_cost = request.execution_plan.get("estimated_cost", 0.0)
        if request.logical_query:
            context.planning_context.logical_intent = request.logical_query.get("intent", "")
