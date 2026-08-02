from typing import Dict
from app.sql_renderer.interfaces import IRendererRegistry, ISQLRenderer

class DeterministicRendererRegistry(IRendererRegistry):
    def __init__(self):
        self._renderers: Dict[str, ISQLRenderer] = {}

    def register(self, renderer: ISQLRenderer) -> None:
        self._renderers[renderer.dialect_name.lower()] = renderer
        
    def get(self, dialect_name: str) -> ISQLRenderer:
        renderer = self._renderers.get(dialect_name.lower())
        if not renderer:
            raise ValueError(f"SQL Renderer for dialect '{dialect_name}' not found.")
        return renderer
