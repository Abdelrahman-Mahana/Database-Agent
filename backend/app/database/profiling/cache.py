from typing import Dict, Optional
from app.database.profiling.models import DatabaseProfile

class ProfilingCache:
    def __init__(self):
        self._cache: Dict[str, DatabaseProfile] = {}

    def get(self, plugin_name: str) -> Optional[DatabaseProfile]:
        return self._cache.get(plugin_name)

    def set(self, plugin_name: str, profile: DatabaseProfile):
        self._cache[plugin_name] = profile

    def clear(self, plugin_name: Optional[str] = None):
        if plugin_name:
            self._cache.pop(plugin_name, None)
        else:
            self._cache.clear()
