from typing import Any
from app.orchestrator.interfaces import IFallbackManager

class FallbackManager(IFallbackManager):
    def execute_fallback(self, error: Exception, context: Any) -> Any:
        # Deterministic fallback logic based on error type
        if isinstance(error, TimeoutError):
            return {"error": "Timeout", "message": "The analytical process took too long. Please simplify your query."}
        return {"error": "InternalFailure", "message": str(error)}
