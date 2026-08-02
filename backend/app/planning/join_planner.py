from typing import List
from app.planning.interfaces import IJoinPlanner
from app.planning.models import ExecutionStep, StepType
from app.query_understanding.models import QueryUnderstanding
from app.database.intelligence.models import SchemaIntelligence

class DeterministicJoinPlanner(IJoinPlanner):
    def plan_joins(self, qu: QueryUnderstanding, intelligence: SchemaIntelligence) -> List[ExecutionStep]:
        steps = []
        tables = qu.entities.tables
        
        # If 0 or 1 table, no joins needed.
        if len(tables) < 2:
            return steps
            
        # Simplified deterministic join planning.
        # We sequentially join tables if they exist in intelligence relationships.
        # In a real engine, this builds a spanning tree based on relationships.
        base_table = tables[0]
        for target_table in tables[1:]:
            steps.append(ExecutionStep(
                step_type=StepType.JOIN,
                parameters={
                    "type": "INNER",
                    "left_table": base_table,
                    "right_table": target_table,
                    "confidence": 0.8 # simplified fixed confidence
                },
                outputs=[f"joined_{base_table}_{target_table}"]
            ))
            base_table = target_table # daisy chain for simplicity in this determinism
            
        return steps
