from abc import ABC, abstractmethod
from typing import Dict, Any, List
from app.context_builder.models import StructuredContext, ContextBuildRequest, ValidationResult, OptimizationMetrics

class IContextExtractor(ABC):
    @abstractmethod
    def extract(self, request: ContextBuildRequest, context: StructuredContext) -> None:
        pass

class ICompressor(ABC):
    @abstractmethod
    def compress(self, context: StructuredContext) -> OptimizationMetrics:
        pass

class IRankingEngine(ABC):
    @abstractmethod
    def rank(self, request: ContextBuildRequest, context: StructuredContext) -> None:
        pass

class ITokenEstimator(ABC):
    @abstractmethod
    def estimate(self, context: StructuredContext) -> int:
        pass

class IContextOptimizer(ABC):
    @abstractmethod
    def optimize(self, request: ContextBuildRequest, context: StructuredContext) -> None:
        pass

class IContextValidator(ABC):
    @abstractmethod
    def validate(self, context: StructuredContext) -> ValidationResult:
        pass

class IBuilder(ABC):
    @abstractmethod
    def build(self, request: ContextBuildRequest) -> StructuredContext:
        pass
