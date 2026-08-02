from abc import ABC, abstractmethod
from typing import List, Dict, Any, Callable
from app.orchestrator.models import UserRequest, OrchestratorResponse, LifecycleState

class IEventBus(ABC):
    @abstractmethod
    def publish(self, event_name: str, payload: Any) -> None:
        pass
    @abstractmethod
    def subscribe(self, event_name: str, callback: Callable) -> None:
        pass

class IStateMachine(ABC):
    @abstractmethod
    def transition(self, current_state: LifecycleState, new_state: LifecycleState) -> None:
        pass
    @abstractmethod
    def get_state(self) -> LifecycleState:
        pass

class IDecisionEngine(ABC):
    @abstractmethod
    def evaluate(self, request: UserRequest, context: Any) -> Any:
        pass

class IContextReuseEngine(ABC):
    @abstractmethod
    def evaluate_reuse(self, context: Any) -> bool:
        pass

class IClarificationEngine(ABC):
    @abstractmethod
    def needs_clarification(self, context: Any) -> bool:
        pass

class IRetryManager(ABC):
    @abstractmethod
    def execute_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        pass

class IFallbackManager(ABC):
    @abstractmethod
    def execute_fallback(self, error: Exception, context: Any) -> Any:
        pass

class ITimeoutManager(ABC):
    @abstractmethod
    def execute_with_timeout(self, func: Callable, timeout_sec: int, *args, **kwargs) -> Any:
        pass

class IRoutingEngine(ABC):
    @abstractmethod
    def route(self, step: str, context: Any) -> Any:
        pass

class IExecutionGraph(ABC):
    @abstractmethod
    def build_graph(self, flags: Any) -> List[str]:
        pass

class IWorkflowEngine(ABC):
    @abstractmethod
    def run(self, graph: List[str], request: UserRequest, response: OrchestratorResponse, event_bus: IEventBus) -> None:
        pass

class IPipeline(ABC):
    @abstractmethod
    def execute(self, request: UserRequest, response: OrchestratorResponse) -> None:
        pass

class IOrchestrator(ABC):
    @abstractmethod
    def process(self, request: UserRequest) -> OrchestratorResponse:
        pass
