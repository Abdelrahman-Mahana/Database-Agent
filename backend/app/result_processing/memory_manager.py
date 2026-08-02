import sys
from typing import Any

class MemoryManager:
    def __init__(self, max_memory_mb: float):
        self.max_memory_mb = max_memory_mb
        self.max_bytes = max_memory_mb * 1024 * 1024
        
    def check_memory_limit(self, obj: Any, current_bytes: int = 0) -> int:
        estimated_size = sys.getsizeof(obj)
        total_size = current_bytes + estimated_size
        if total_size > self.max_bytes:
            raise MemoryError(f"Result processing exceeded maximum memory limit of {self.max_memory_mb} MB")
        return total_size
