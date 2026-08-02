import threading
from typing import Optional
from app.database.discovery.models import DatabaseMetadata

class DiscoveryCache:
    """
    Thread-safe in-memory cache for database metadata.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._cache: Optional[DatabaseMetadata] = None

    def get(self) -> Optional[DatabaseMetadata]:
        with self._lock:
            return self._cache

    def set(self, metadata: DatabaseMetadata) -> None:
        with self._lock:
            self._cache = metadata

    def clear(self) -> None:
        with self._lock:
            self._cache = None
