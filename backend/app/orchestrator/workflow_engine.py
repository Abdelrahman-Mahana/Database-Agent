import time
from typing import List
from app.orchestrator.interfaces import IWorkflowEngine, IRoutingEngine, IStateMachine, IEventBus
from app.orchestrator.models import UserRequest, OrchestratorResponse, LifecycleState

class WorkflowEngine(IWorkflowEngine):
    def __init__(self, routing_engine: IRoutingEngine, state_machine: IStateMachine):
        self.routing_engine = routing_engine
        self.state_machine = state_machine
        
        # Mapping steps to specific lifecycle events
        self.event_map = {
            "conversation": "RequestReceived",
            "query_understanding": "QueryUnderstood",
            "execution": "SQLExecuted",
            "semantic_analysis": "SemanticAnalysisCompleted",
            "context_builder": "ContextBuilt",
            "ai_reasoning": "AnswerGenerated"
        }

    def run(self, graph: List[str], request: UserRequest, response: OrchestratorResponse, event_bus: IEventBus) -> None:
        current_payload = request
        
        for step in graph:
            start_t = time.time()
            try:
                service = self.routing_engine.route(step, current_payload)
                response.pipeline_steps.append(step)
                
                # Mock execution: passing current_payload down.
                # In actual implementation: current_payload = service.process(current_payload)
                
                event_name = self.event_map.get(step)
                if event_name:
                    event_bus.publish(event_name, {"step": step, "request_id": response.request_id})
                    
            except Exception as e:
                response.error_message = str(e)
                self.state_machine.transition(self.state_machine.get_state(), LifecycleState.FAILED)
                event_bus.publish("RequestFailed", {"error": str(e), "step": step})
                raise e
            finally:
                response.timings.stage_durations[step] = (time.time() - start_t) * 1000
