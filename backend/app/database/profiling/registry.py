from typing import Type
from app.database.profiling.interfaces import IColumnProfiler

class ProfilerRegistry:
    def __init__(self):
        self._profilers = {}

    def register(self, name: str, profiler: IColumnProfiler):
        self._profilers[name] = profiler

    def get(self, name: str) -> IColumnProfiler:
        return self._profilers.get(name)

registry = ProfilerRegistry()
