from abc import ABC, abstractmethod
from typing import List, Dict, Any
from app.context_builder.models import StructuredContext
from app.ai_reasoning.models import (
    AIResponse, LLMResponse, ReasoningTrace, Citation, Recommendation, AIReasoningRequest
)

class ILLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> LLMResponse:
        pass

class IProviderRouter(ABC):
    @abstractmethod
    def get_provider(self, name: str = None) -> ILLMProvider:
        pass

class IPromptBuilder(ABC):
    @abstractmethod
    def build(self, question: str, context: StructuredContext) -> str:
        pass

class IReasoningTraceBuilder(ABC):
    @abstractmethod
    def build(self, llm_response: LLMResponse, context: StructuredContext) -> ReasoningTrace:
        pass

class IHallucinationGuard(ABC):
    @abstractmethod
    def validate(self, answer: str, context: StructuredContext) -> List[str]:
        pass

class IResponseValidator(ABC):
    @abstractmethod
    def validate(self, response: AIResponse) -> bool:
        pass

class ICitationBuilder(ABC):
    @abstractmethod
    def build(self, answer: str, context: StructuredContext) -> List[Citation]:
        pass

class IConfidenceEngine(ABC):
    @abstractmethod
    def compute(self, context: StructuredContext, trace: ReasoningTrace, guard_failures: List[str]) -> float:
        pass

class IRecommendationEngine(ABC):
    @abstractmethod
    def generate(self, answer: str, context: StructuredContext) -> List[Recommendation]:
        pass

class IFollowupGenerator(ABC):
    @abstractmethod
    def generate(self, answer: str, context: StructuredContext) -> List[str]:
        pass

class IExplanationEngine(ABC):
    @abstractmethod
    def explain(self, text: str) -> str:
        pass

class IAnswerGenerator(ABC):
    @abstractmethod
    def generate(self, question: str, context: StructuredContext, provider: ILLMProvider) -> AIResponse:
        pass

class IReasoningEngine(ABC):
    @abstractmethod
    def reason(self, request: AIReasoningRequest, context: StructuredContext) -> AIResponse:
        pass
