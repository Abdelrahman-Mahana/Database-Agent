from typing import List
import re
from app.planning.interfaces import ILimitPlanner
from app.planning.models import ExecutionStep, StepType
from app.query_understanding.models import QueryUnderstanding, QueryIntent

class DeterministicLimitPlanner(ILimitPlanner):
    def plan_limits(self, qu: QueryUnderstanding) -> List[ExecutionStep]:
        steps = []
        
        limit_val = None
        
        # Extract limit number deterministically if intent demands it
        if qu.intent in [QueryIntent.TOP_K, QueryIntent.BOTTOM_K]:
            # very naive extraction for "top 5", "bottom 10"
            matches = re.findall(r'\b(?:top|bottom)\s+(\d+)\b', qu.normalized_query)
            if matches:
                limit_val = int(matches[0])
            else:
                limit_val = 10 # default
                
        if limit_val:
            steps.append(ExecutionStep(
                step_type=StepType.LIMIT,
                parameters={"limit": limit_val, "offset": 0}
            ))
            
        return steps
