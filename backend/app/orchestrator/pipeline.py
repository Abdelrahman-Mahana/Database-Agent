import time
from app.orchestrator.interfaces import (
    IPipeline, IExecutionGraph, IWorkflowEngine, IDecisionEngine,
    IContextReuseEngine, IClarificationEngine, IStateMachine, IEventBus
)
from app.orchestrator.models import UserRequest, OrchestratorResponse, LifecycleState

class Pipeline(IPipeline):
    def __init__(
        self,
        execution_graph: IExecutionGraph,
        workflow_engine: IWorkflowEngine,
        decision_engine: IDecisionEngine,
        reuse_engine: IContextReuseEngine,
        clarification_engine: IClarificationEngine,
        state_machine: IStateMachine,
        event_bus: IEventBus
    ):
        self.execution_graph = execution_graph
        self.workflow_engine = workflow_engine
        self.decision_engine = decision_engine
        self.reuse_engine = reuse_engine
        self.clarification_engine = clarification_engine
        self.state_machine = state_machine
        self.event_bus = event_bus

    def execute(self, request: UserRequest, response: OrchestratorResponse) -> None:
        self.state_machine.transition(LifecycleState.RECEIVED, LifecycleState.VALIDATED)
        
        flags = self.decision_engine.evaluate(request, None)
        response.decision_trace = flags
        
        if flags.ask_clarification:
            response.warnings.append("Clarification needed")
            self.state_machine.transition(LifecycleState.VALIDATED, LifecycleState.FAILED)
            self.event_bus.publish("RequestFailed", {"reason": "Clarification needed"})
            return
            
        graph = self.execution_graph.build_graph(flags)
        response.execution_path = graph
        
        self.workflow_engine.run(graph, request, response, self.event_bus)
        
        self.state_machine.transition(self.state_machine.get_state(), LifecycleState.COMPLETED)
        response.state = self.state_machine.get_state()
        self.event_bus.publish("RequestCompleted", {"request_id": response.request_id})
