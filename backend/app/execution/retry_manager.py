import time
from typing import Callable, Any, Tuple

class RetryManager:
    def __init__(self, max_retries: int = 3, base_delay: float = 0.5):
        self.max_retries = max_retries
        self.base_delay = base_delay
        
    def is_transient_error(self, error: Exception) -> bool:
        error_msg = str(error).lower()
        transient_keywords = [
            "deadlock",
            "timeout",
            "connection reset",
            "network error",
            "server gone away"
        ]
        return any(k in error_msg for k in transient_keywords)
        
    def execute_with_retry_tracked(self, func: Callable[[], Any]) -> Tuple[Any, int]:
        retries = 0
        while True:
            try:
                res = func()
                return res, retries
            except Exception as e:
                if not self.is_transient_error(e) or retries >= self.max_retries:
                    raise e
                time.sleep(self.base_delay * (2 ** retries))
                retries += 1

    def execute_with_retry(self, func: Callable[[], Any]) -> Any:
        res, _ = self.execute_with_retry_tracked(func)
        return res
