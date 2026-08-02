from typing import List, Callable, Optional, Dict
from pydantic import BaseModel
from app.orchestrator.interfaces import IExecutionGraph
from app.orchestrator.models import DecisionFlags

class GraphNode(BaseModel):
    name: str
    dependencies: List[str] = []

class ExecutionGraph(IExecutionGraph):
    def build_graph(self, flags: DecisionFlags) -> List[str]:
        # Represented as a true DAG, filtered by conditions
        nodes = [
            ("conversation", lambda f: True),
            ("query_understanding", lambda f: True),
            ("database_discovery", lambda f: not f.skip_discovery),
            ("schema_intelligence", lambda f: f.refresh_metadata or not f.skip_discovery),
            ("execution_planning", lambda f: not f.reuse_context),
            ("logical_query", lambda f: not f.reuse_context),
            ("sql_rendering", lambda f: not f.reuse_context),
            ("sql_validation", lambda f: not f.reuse_context),
            ("execution", lambda f: f.execute_sql and not f.reuse_context and not f.reuse_semantic),
            ("result_processing", lambda f: f.execute_sql and not f.reuse_context and not f.reuse_semantic),
            ("semantic_analysis", lambda f: not f.reuse_semantic and not f.reuse_context),
            ("context_builder", lambda f: not f.reuse_context),
            ("ai_reasoning", lambda f: True)
        ]
        
        execution_path = []
        for name, condition in nodes:
            if condition(flags):
                execution_path.append(name)
                
        return execution_path
