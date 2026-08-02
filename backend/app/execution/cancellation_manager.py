from threading import Lock
from typing import Set, Dict, Callable

class CancellationManager:
    def __init__(self):
        self._lock = Lock()
        self._cancelled_ids: Set[str] = set()
        self._active_ids: Set[str] = set()
        self._driver_hooks: Dict[str, Callable[[], bool]] = {}
        
    def register(self, execution_id: str, driver_hook: Callable[[], bool] = None) -> None:
        with self._lock:
            self._active_ids.add(execution_id)
            self._cancelled_ids.discard(execution_id)
            if driver_hook:
                self._driver_hooks[execution_id] = driver_hook
            
    def cancel(self, execution_id: str) -> bool:
        hook_to_call = None
        with self._lock:
            if execution_id in self._active_ids:
                self._cancelled_ids.add(execution_id)
                hook_to_call = self._driver_hooks.get(execution_id)
                
        if hook_to_call:
            try:
                hook_to_call()
            except Exception:
                pass
                
        return execution_id in self._active_ids
            
    def is_cancelled(self, execution_id: str) -> bool:
        with self._lock:
            return execution_id in self._cancelled_ids
            
    def unregister(self, execution_id: str) -> None:
        with self._lock:
            self._active_ids.discard(execution_id)
            self._cancelled_ids.discard(execution_id)
            self._driver_hooks.pop(execution_id, None)
