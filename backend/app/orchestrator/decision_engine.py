from typing import Any
from app.orchestrator.interfaces import IDecisionEngine
from app.orchestrator.models import UserRequest, DecisionFlags

class DecisionEngine(IDecisionEngine):
    def evaluate(self, request: UserRequest, context: Any) -> DecisionFlags:
        flags = DecisionFlags()
        
        # 1. Force refresh overrides everything
        if request.force_refresh:
            flags.refresh_metadata = True
            flags.skip_discovery = False
            return flags
            
        # 2. Schema changes invalidate caching
        if request.schema_version_changed:
            flags.refresh_metadata = True
            flags.skip_discovery = False
            
        # 3. Cache & Semantic reuse
        if request.cache_available and request.query_compatible and request.context_ttl_valid:
            flags.reuse_semantic = True
            flags.execute_sql = False
            
        # 4. Context Reuse
        if request.context_ttl_valid and request.query_compatible and not request.schema_version_changed:
            flags.reuse_context = True
            flags.execute_sql = False
            flags.skip_discovery = True
            
        # 5. Clarification
        # In a real environment, conversational state or validation might trigger this
        if not request.question:
            flags.ask_clarification = True
            
        return flags
