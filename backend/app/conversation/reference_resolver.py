from typing import List, Dict
import re
from app.conversation.interfaces import IReferenceResolver
from app.conversation.models import MemoryContext, TrackedEntity

class ReferenceResolver(IReferenceResolver):
    def resolve(self, text: str, entities: List[TrackedEntity], memory: MemoryContext) -> Dict[str, TrackedEntity]:
        resolved = {}
        text_lower = text.lower()
        references = ["them", "those", "that", "it", "they"]
        
        for ref in references:
            if re.search(r'\b' + ref + r'\b', text_lower):
                # Attempt resolution from memory active entities
                if memory.active_entities:
                    # Deterministic resolution: Pick highest confidence active entity
                    top_entity = sorted(memory.active_entities.values(), key=lambda e: e.confidence, reverse=True)[0]
                    resolved[ref] = top_entity
                    
        return resolved
