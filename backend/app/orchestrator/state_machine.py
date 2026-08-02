from app.orchestrator.interfaces import IStateMachine
from app.orchestrator.models import LifecycleState

class StateMachine(IStateMachine):
    def __init__(self, event_bus):
        self.state = LifecycleState.RECEIVED
        self.event_bus = event_bus
        
        self.valid_transitions = {
            LifecycleState.RECEIVED: [LifecycleState.VALIDATED, LifecycleState.FAILED],
            LifecycleState.VALIDATED: [LifecycleState.UNDERSTOOD, LifecycleState.FAILED],
            LifecycleState.UNDERSTOOD: [LifecycleState.PLANNED, LifecycleState.CONTEXT_READY, LifecycleState.FAILED],
            LifecycleState.PLANNED: [LifecycleState.EXECUTED, LifecycleState.FAILED],
            LifecycleState.EXECUTED: [LifecycleState.PROCESSED, LifecycleState.FAILED],
            LifecycleState.PROCESSED: [LifecycleState.ANALYZED, LifecycleState.FAILED],
            LifecycleState.ANALYZED: [LifecycleState.CONTEXT_READY, LifecycleState.FAILED],
            LifecycleState.CONTEXT_READY: [LifecycleState.ANSWER_GENERATED, LifecycleState.FAILED],
            LifecycleState.ANSWER_GENERATED: [LifecycleState.COMPLETED, LifecycleState.FAILED],
            LifecycleState.COMPLETED: [],
            LifecycleState.FAILED: []
        }

    def transition(self, current_state: LifecycleState, new_state: LifecycleState) -> None:
        if self.state != current_state:
            raise ValueError(f"State mismatch: expected {current_state}, got {self.state}")
            
        allowed = self.valid_transitions.get(current_state, [])
        if new_state not in allowed:
            raise ValueError(f"Invalid transition from {current_state} to {new_state}")
            
        self.state = new_state
        self.event_bus.publish("state_changed", {"from": current_state, "to": new_state})
        
    def get_state(self) -> LifecycleState:
        return self.state
