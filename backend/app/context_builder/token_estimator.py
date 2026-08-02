from abc import ABC, abstractmethod
import json
from app.context_builder.interfaces import ITokenEstimator
from app.context_builder.models import StructuredContext

class ITokenProvider(ABC):
    @abstractmethod
    def estimate(self, text: str) -> int:
        pass

class OpenAITokenProvider(ITokenProvider):
    def estimate(self, text: str) -> int:
        # Placeholder for tiktoken logic
        return max(1, len(text) // 4)

class GeminiTokenProvider(ITokenProvider):
    def estimate(self, text: str) -> int:
        # Placeholder for google.generativeai tokenization
        return max(1, len(text) // 4)

class ClaudeTokenProvider(ITokenProvider):
    def estimate(self, text: str) -> int:
        # Placeholder for anthropic tokenization
        return max(1, len(text) // 4)

class TokenEstimator(ITokenEstimator):
    def __init__(self, provider: ITokenProvider):
        self.provider = provider
        
    def estimate(self, context: StructuredContext) -> int:
        text_rep = json.dumps(context.model_dump(), default=str)
        return self.provider.estimate(text_rep)
