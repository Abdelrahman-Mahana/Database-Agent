from app.context_builder.interfaces import IContextExtractor
from app.context_builder.models import StructuredContext, ContextBuildRequest

class QuestionContextExtractor(IContextExtractor):
    def extract(self, request: ContextBuildRequest, context: StructuredContext) -> None:
        if request.query_understanding:
            context.question_context.parsed_question = request.query_understanding.get("parsed_question", {})
            context.question_context.business_terms = request.query_understanding.get("business_terms", [])
            context.question_context.entities = request.query_understanding.get("entities", [])
            
            context.business_terms = request.query_understanding.get("business_terms", [])
            context.relevant_entities = request.query_understanding.get("entities", [])
