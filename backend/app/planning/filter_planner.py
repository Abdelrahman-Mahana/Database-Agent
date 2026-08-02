from typing import List
from app.planning.interfaces import IFilterPlanner
from app.planning.models import ExecutionStep, StepType
from app.query_understanding.models import QueryUnderstanding

class DeterministicFilterPlanner(IFilterPlanner):
    def plan_filters(self, qu: QueryUnderstanding) -> List[ExecutionStep]:
        steps = []
        
        # Regular filters
        for f in qu.filters:
            steps.append(ExecutionStep(
                step_type=StepType.FILTER,
                parameters={
                    "field": f.field,
                    "operator": f.operator.value,
                    "value": f.value
                }
            ))
            
        # Time filters
        if qu.time_range and qu.time_range.expression:
            steps.append(ExecutionStep(
                step_type=StepType.FILTER,
                parameters={
                    "time_expression": qu.time_range.expression,
                    "start_time": qu.time_range.start_time.isoformat() if qu.time_range.start_time else None,
                    "end_time": qu.time_range.end_time.isoformat() if qu.time_range.end_time else None
                }
            ))
            
        return steps
