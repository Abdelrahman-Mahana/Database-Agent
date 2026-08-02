from typing import Optional
from app.logical_query.interfaces import ISortBuilder
from app.logical_query.models import LogicalSort, LogicalOrder, LogicalColumn, SortDirection
from app.planning.models import ExecutionPlan, StepType

class DeterministicSortBuilder(ISortBuilder):
    def build_sorts(self, plan: ExecutionPlan) -> Optional[LogicalSort]:
        sort = LogicalSort()
        for step in plan.graph.steps:
            if step.step_type == StepType.SORT:
                for key in step.parameters.get("keys", []):
                    field = key.get("field", "unknown")
                    dir_str = key.get("direction", "ASC")
                    
                    try:
                        direction = SortDirection(dir_str)
                    except ValueError:
                        direction = SortDirection.ASC
                        
                    sort.orders.append(LogicalOrder(
                        expression=LogicalColumn(column_name=field),
                        direction=direction
                    ))
                    
        return sort if sort.orders else None
