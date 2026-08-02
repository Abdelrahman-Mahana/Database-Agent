from typing import List, Optional
import re
from app.conversation.interfaces import IEntityTracker
from app.conversation.models import TrackedEntity, TrackedTable
from app.context_builder.models import StructuredContext

class EntityTracker(IEntityTracker):
    def track(self, session_id: str, text: str, context: Optional[StructuredContext]) -> List[TrackedEntity]:
        entities = []
        text_lower = text.lower()
        
        # Resolve from schema context explicitly
        if context and context.schema_context:
            for t_name, t_data in context.schema_context.tables.items():
                if t_name.lower() in text_lower:
                    entities.append(TrackedEntity(
                        entity_type="table",
                        name=t_name,
                        table=TrackedTable(name=t_name),
                        confidence=1.0
                    ))
        
        # Resolve from business terms natively
        if context and context.business_terms:
            for term in context.business_terms:
                if term.lower() in text_lower:
                    entities.append(TrackedEntity(
                        entity_type="business_term",
                        name=term,
                        confidence=1.0
                    ))
                    
        # Remove duplicates
        unique_entities = {e.name: e for e in entities}
        return list(unique_entities.values())
