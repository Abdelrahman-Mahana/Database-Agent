from typing import Optional
from app.logical_query.interfaces import ILimitBuilder
from app.logical_query.models import LogicalLimit
from app.planning.models import ExecutionPlan, StepType

class DeterministicLimitBuilder(ILimitBuilder):
    def build_limits(self, plan: ExecutionPlan) -> Optional[LogicalLimit]:
        for step in plan.graph.steps:
            if step.step_type == StepType.LIMIT:
                limit_val = step.parameters.get("limit", 100)
                offset_val = step.parameters.get("offset", 0)
                return LogicalLimit(limit=limit_val, offset=offset_val)
        return None
