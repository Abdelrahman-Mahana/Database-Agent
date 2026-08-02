from typing import Optional
from app.logical_query.interfaces import IFilterBuilder
from app.logical_query.models import LogicalFilter, LogicalExpression, LogicalOperator, LogicalColumn, LogicalLiteral
from app.planning.models import ExecutionPlan, StepType

class DeterministicFilterBuilder(IFilterBuilder):
    def build_filters(self, plan: ExecutionPlan) -> Optional[LogicalFilter]:
        filters = []
        for step in plan.graph.steps:
            if step.step_type == StepType.FILTER:
                field = step.parameters.get("field")
                if not field:
                    continue
                operator = step.parameters.get("operator", "EQUALS").upper()
                value = step.parameters.get("value")
                
                # Safely map to LogicalOperator
                try:
                    op = LogicalOperator(operator)
                except ValueError:
                    op = LogicalOperator.EQUALS
                    
                expr = LogicalExpression(
                    expr_type=op,
                    children=[
                        LogicalColumn(column_name=field),
                        LogicalLiteral(value=value)
                    ]
                )
                filters.append(expr)
                
        if not filters:
            return None
            
        if len(filters) == 1:
            return LogicalFilter(condition=filters[0])
            
        # Combine with AND
        and_expr = LogicalExpression(
            expr_type=LogicalOperator.AND,
            children=filters
        )
        return LogicalFilter(condition=and_expr)
