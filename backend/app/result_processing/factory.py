from app.result_processing.registry import NormalizerRegistry
from app.result_processing.interfaces import ITypeNormalizer

class ProcessorFactory:
    def __init__(self, registry: NormalizerRegistry, default_normalizer: ITypeNormalizer):
        self.registry = registry
        self.default_normalizer = default_normalizer
        
    def get_normalizer(self, dialect: str) -> ITypeNormalizer:
        return self.registry.get(dialect, self.default_normalizer)
