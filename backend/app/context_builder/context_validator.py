from app.context_builder.interfaces import IContextValidator
from app.context_builder.models import StructuredContext, ValidationResult

class ContextValidator(IContextValidator):
    def validate(self, context: StructuredContext) -> ValidationResult:
        result = ValidationResult()
        
        if not context.schema_context.tables:
            result.missing_context.append("Schema Summary is missing")
            result.is_valid = False
            
        if not context.question_context.parsed_question and not context.question_context.entities:
            result.missing_context.append("Question Summary is missing")
            
        if not context.execution_context.schema_def and not context.planning_context.nodes:
            result.missing_context.append("Both Execution and Planning Contexts are missing")
            
        return result
