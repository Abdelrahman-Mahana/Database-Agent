from app.ai_reasoning.interfaces import IResponseValidator
from app.ai_reasoning.models import AIResponse

class ResponseValidator(IResponseValidator):
    def validate(self, response: AIResponse) -> bool:
        if not response.answer:
            response.warnings.append("Empty answer generated.")
            return False
            
        if response.confidence < 0.3:
            response.warnings.append("Critically low confidence response.")
            
        return True
