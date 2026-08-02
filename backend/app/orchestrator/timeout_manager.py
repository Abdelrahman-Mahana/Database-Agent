import concurrent.futures
from typing import Callable, Any
from app.orchestrator.interfaces import ITimeoutManager

class TimeoutManager(ITimeoutManager):
    def execute_with_timeout(self, func: Callable, timeout_sec: int, *args, **kwargs) -> Any:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            try:
                return future.result(timeout=timeout_sec)
            except concurrent.futures.TimeoutError:
                raise TimeoutError(f"Function execution exceeded {timeout_sec} seconds timeout")
