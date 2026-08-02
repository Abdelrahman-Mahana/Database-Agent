from app.conversation.interfaces import IConversationValidator
from app.conversation.models import ConversationContext, ValidationResult

class ConversationValidator(IConversationValidator):
    def validate(self, ctx: ConversationContext) -> ValidationResult:
        result = ValidationResult()
        
        # Check ambiguous references
        if "it" in ctx.resolved_question.lower() and not ctx.resolved_references:
            result.ambiguous_references.append("it")
            result.warnings.append("Ambiguous reference 'it' could not be resolved from memory.")
            
        # Check missing entities
        if not ctx.resolved_entities and len(ctx.resolved_question.split()) > 3:
             result.warnings.append("No recognizable entities found in question.")
             
        # Determine validity
        if len(result.ambiguous_references) > 2:
            result.is_valid = False
            
        return result
