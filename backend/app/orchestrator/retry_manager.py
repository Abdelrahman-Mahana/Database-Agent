import time
from typing import Callable, Any
from app.orchestrator.interfaces import IRetryManager

class RetryManager(IRetryManager):
    def __init__(self, max_retries: int = 3, backoff_factor: float = 1.5):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        
    def execute_with_retry(self, func: Callable, *args, **kwargs) -> Any:
        attempts = 0
        while attempts < self.max_retries:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                attempts += 1
                if attempts >= self.max_retries:
                    raise e
                time.sleep(self.backoff_factor ** attempts)
