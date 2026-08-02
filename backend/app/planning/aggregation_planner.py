from typing import List
from app.planning.interfaces import IAggregationPlanner
from app.planning.models import ExecutionStep, StepType, AggregationFunction
from app.query_understanding.models import QueryUnderstanding, QueryIntent

class DeterministicAggregationPlanner(IAggregationPlanner):
    def plan_aggregations(self, qu: QueryUnderstanding) -> List[ExecutionStep]:
        steps = []
        
        if qu.intent not in [QueryIntent.AGGREGATION, QueryIntent.COUNT, QueryIntent.SUMMARY]:
            return steps
            
        if qu.dimensions:
            steps.append(ExecutionStep(
                step_type=StepType.GROUP_BY,
                parameters={
                    "dimensions": qu.dimensions
                }
            ))
            
        if qu.metrics:
            aggs = []
            func = AggregationFunction.SUM
            if "avg" in qu.normalized_query or "average" in qu.normalized_query:
                func = AggregationFunction.AVG
            elif qu.intent == QueryIntent.COUNT:
                func = AggregationFunction.COUNT
                
            for m in qu.metrics:
                aggs.append({"field": m, "function": func.value})
                
            steps.append(ExecutionStep(
                step_type=StepType.AGGREGATE,
                parameters={
                    "aggregations": aggs
                }
            ))
            
        return steps
