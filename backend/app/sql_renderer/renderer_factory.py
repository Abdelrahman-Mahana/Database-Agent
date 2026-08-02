from app.sql_renderer.interfaces import IRendererFactory, IRendererRegistry, ISQLRenderer

class DeterministicRendererFactory(IRendererFactory):
    def __init__(self, registry: IRendererRegistry):
        self.registry = registry
        
    def get_renderer(self, dialect_name: str) -> ISQLRenderer:
        return self.registry.get(dialect_name)
