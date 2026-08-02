from app.context_builder.models import StructuredContext
from app.ai_reasoning.interfaces import IAnswerGenerator, IPromptBuilder, ILLMProvider
from app.ai_reasoning.models import AIResponse, ResponseMetadata

class AnswerGenerator(IAnswerGenerator):
    def __init__(self, prompt_builder: IPromptBuilder):
        self.prompt_builder = prompt_builder

    def generate(self, question: str, context: StructuredContext, provider: ILLMProvider) -> AIResponse:
        prompt = self.prompt_builder.build(question, context)
        llm_response = provider.generate(prompt)
        
        response = AIResponse()
        response.answer = llm_response.text
        response.response_metadata = ResponseMetadata(
            provider_used=llm_response.model,
            tokens_used=llm_response.tokens_used
        )
        
        return response
