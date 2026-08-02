from typing import List
from app.planning.interfaces import IStepBuilder
from app.planning.models import ExecutionStep, StepType
from app.query_understanding.models import QueryUnderstanding

class DeterministicStepBuilder(IStepBuilder):
    def build(self, qu: QueryUnderstanding) -> List[ExecutionStep]:
        steps = []
        
        # Initial scans for all tables
        for table in qu.entities.tables:
            steps.append(ExecutionStep(
                step_type=StepType.SCAN_TABLE,
                parameters={"table_name": table},
                outputs=[table]
            ))
            
        # Projection (which columns to return directly if no aggregation)
        if not qu.metrics and qu.entities.columns:
            steps.append(ExecutionStep(
                step_type=StepType.PROJECT,
                parameters={"columns": qu.entities.columns}
            ))
            
        return steps
