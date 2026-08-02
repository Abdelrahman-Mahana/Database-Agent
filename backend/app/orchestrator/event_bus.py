from pydantic import BaseModel
from typing import Any, Callable, Dict, List
from app.orchestrator.interfaces import IEventBus
import structlog

logger = structlog.get_logger(__name__)

class EventBus(IEventBus):
    def __init__(self):
        self._subscribers: Dict[str, List[Callable]] = {}
        
    def publish(self, event_name: str, payload: Any) -> None:
        logger.debug(f"Event published: {event_name}")
        for callback in self._subscribers.get(event_name, []):
            try:
                callback(payload)
            except Exception as e:
                logger.error("Error in event subscriber", event=event_name, error=str(e))
                
    def subscribe(self, event_name: str, callback: Callable) -> None:
        if event_name not in self._subscribers:
            self._subscribers[event_name] = []
        self._subscribers[event_name].append(callback)
