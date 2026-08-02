import signal
from contextlib import contextmanager
from typing import Generator

class TimeoutError(Exception):
    pass

class TimeoutManager:
    @contextmanager
    def enforce_timeout(self, seconds: int) -> Generator[None, None, None]:
        def timeout_handler(signum, frame):
            raise TimeoutError(f"Execution timed out after {seconds} seconds.")
            
        original_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(seconds)
        
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, original_handler)
