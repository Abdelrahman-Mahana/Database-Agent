from typing import List
from app.logical_query.interfaces import IJoinGraph
from app.logical_query.models import LogicalJoin, JoinType, LogicalRelation, LogicalExpression, LogicalOperator
from app.planning.models import ExecutionPlan, StepType

class DeterministicJoinGraph(IJoinGraph):
    def build_joins(self, plan: ExecutionPlan) -> List[LogicalJoin]:
        joins = []
        for step in plan.graph.steps:
            if step.step_type == StepType.JOIN:
                # Deterministic translation
                p = step.parameters
                left = LogicalRelation(table_name=p.get("left_table", "unknown_left"))
                right = LogicalRelation(table_name=p.get("right_table", "unknown_right"))
                
                # Assume EQUALS operator for join condition
                condition = LogicalExpression(
                    expr_type=LogicalOperator.EQUALS, # Treating operator as expression root
                    children=[]
                )
                
                joins.append(LogicalJoin(
                    join_type=JoinType.INNER,
                    left_relation=left,
                    right_relation=right,
                    condition=condition
                ))
        return joins
