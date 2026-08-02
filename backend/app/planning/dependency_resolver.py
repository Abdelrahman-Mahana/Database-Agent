from typing import List
from app.planning.interfaces import IDependencyResolver
from app.planning.models import ExecutionStep, ExecutionDependency, ExecutionGraph, StepType, DependencyType

class DeterministicDependencyResolver(IDependencyResolver):
    def resolve(self, steps: List[ExecutionStep]) -> ExecutionGraph:
        # A simple linear resolution based on order of operations
        # SCAN -> JOIN -> FILTER -> GROUP_BY -> AGGREGATE -> SORT -> LIMIT
        
        order_priority = {
            StepType.SCAN_TABLE: 1,
            StepType.JOIN: 2,
            StepType.FILTER: 3,
            StepType.GROUP_BY: 4,
            StepType.AGGREGATE: 5,
            StepType.PROJECT: 6,
            StepType.SORT: 7,
            StepType.LIMIT: 8
        }
        
        # Sort steps by execution priority
        sorted_steps = sorted(steps, key=lambda s: order_priority.get(s.step_type, 99))
        
        dependencies = []
        for i in range(len(sorted_steps) - 1):
            source = sorted_steps[i]
            target = sorted_steps[i + 1]
            
            # Simple linear dependency injection
            target.inputs.append(source.step_id)
            dependencies.append(ExecutionDependency(
                source_step_id=source.step_id,
                target_step_id=target.step_id,
                dependency_type=DependencyType.DATA
            ))
            
        return ExecutionGraph(steps=sorted_steps, dependencies=dependencies)
