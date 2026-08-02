from app.logical_query.interfaces import IProjectionBuilder
from app.logical_query.models import LogicalProjection, LogicalColumn
from app.planning.models import ExecutionPlan, StepType

class DeterministicProjectionBuilder(IProjectionBuilder):
    def build_projections(self, plan: ExecutionPlan) -> LogicalProjection:
        proj = LogicalProjection()
        for step in plan.graph.steps:
            if step.step_type == StepType.PROJECT:
                for col in step.parameters.get("columns", []):
                    proj.expressions.append(LogicalColumn(column_name=col))
        return proj
