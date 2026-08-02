from typing import List
from app.planning.interfaces import ISortPlanner
from app.planning.models import ExecutionStep, StepType, SortDirection
from app.query_understanding.models import QueryUnderstanding, QueryIntent

class DeterministicSortPlanner(ISortPlanner):
    def plan_sorts(self, qu: QueryUnderstanding) -> List[ExecutionStep]:
        steps = []
        
        if qu.intent == QueryIntent.TOP_K:
            sort_keys = [{"field": m, "direction": SortDirection.DESC.value} for m in qu.metrics]
            if sort_keys:
                steps.append(ExecutionStep(
                    step_type=StepType.SORT,
                    parameters={"keys": sort_keys}
                ))
                
        elif qu.intent == QueryIntent.BOTTOM_K:
            sort_keys = [{"field": m, "direction": SortDirection.ASC.value} for m in qu.metrics]
            if sort_keys:
                steps.append(ExecutionStep(
                    step_type=StepType.SORT,
                    parameters={"keys": sort_keys}
                ))
                
        # We could also check for "order by" explicitly in the future.
        return steps
