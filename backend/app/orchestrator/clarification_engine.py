from typing import Any
from app.orchestrator.interfaces import IClarificationEngine

class ClarificationEngine(IClarificationEngine):
    def needs_clarification(self, context: Any) -> bool:
        # Check validation warnings from conversation engine
        if hasattr(context, "validation") and not context.validation.is_valid:
            return True
        return False
