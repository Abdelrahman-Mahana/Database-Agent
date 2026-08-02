# Placeholder for any needed factory/registry
# e.g., if we had dialect-specific normalizers, we'd register them here.
from typing import Dict
from app.result_processing.interfaces import ITypeNormalizer

class NormalizerRegistry:
    def __init__(self):
        self._normalizers: Dict[str, ITypeNormalizer] = {}
        
    def register(self, dialect: str, normalizer: ITypeNormalizer):
        self._normalizers[dialect.upper()] = normalizer
        
    def get(self, dialect: str, default: ITypeNormalizer) -> ITypeNormalizer:
        return self._normalizers.get(dialect.upper(), default)
