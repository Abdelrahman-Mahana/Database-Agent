from typing import Any
from app.orchestrator.interfaces import IContextReuseEngine

class ContextReuseEngine(IContextReuseEngine):
    def evaluate_reuse(self, context: Any) -> bool:
        # Deterministically decide if entire pipeline can be skipped based on conversation context reuse flag
        if hasattr(context, "reused_context") and context.reused_context.was_reused:
            if context.reused_context.decision == "REUSE_CONTEXT":
                return True
        return False
