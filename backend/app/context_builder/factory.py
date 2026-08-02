from app.context_builder.interfaces import IBuilder

class BuilderRegistry:
    def __init__(self):
        self._builders = {}
        
    def register(self, name: str, builder: IBuilder):
        self._builders[name.upper()] = builder
        
    def get(self, name: str) -> IBuilder:
        return self._builders.get(name.upper())

class BuilderFactory:
    def __init__(self, registry: BuilderRegistry, default_builder: IBuilder):
        self.registry = registry
        self.default_builder = default_builder
        
    def get_builder(self, domain: str = None) -> IBuilder:
        if domain:
            b = self.registry.get(domain)
            if b: return b
        return self.default_builder
