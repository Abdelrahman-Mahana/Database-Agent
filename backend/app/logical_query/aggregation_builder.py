from typing import Optional
from app.logical_query.interfaces import IAggregationBuilder
from app.logical_query.models import LogicalGroup, LogicalColumn, LogicalAlias, LogicalExpression, AggregationType
from app.planning.models import ExecutionPlan, StepType

class DeterministicAggregationBuilder(IAggregationBuilder):
    def build_aggregations(self, plan: ExecutionPlan) -> Optional[LogicalGroup]:
        group = LogicalGroup()
        has_agg = False
        
        for step in plan.graph.steps:
            if step.step_type == StepType.GROUP_BY:
                has_agg = True
                for dim in step.parameters.get("dimensions", []):
                    group.grouping_expressions.append(LogicalColumn(column_name=dim))
            elif step.step_type == StepType.AGGREGATE:
                has_agg = True
                for agg in step.parameters.get("aggregations", []):
                    # We map agg func straight over, assuming it exists
                    func_name = agg.get("function", "SUM")
                    field_name = agg.get("field", "unknown")
                    
                    # Create LogicalAlias enclosing LogicalExpression (mock function logic)
                    expr = LogicalExpression(
                        expr_type=AggregationType(func_name),
                        value=field_name
                    )
                    group.aggregations.append(LogicalAlias(expression=expr, alias=f"{func_name.lower()}_{field_name}"))
                    
        return group if has_agg else None
