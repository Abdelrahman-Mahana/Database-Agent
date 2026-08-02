from typing import Dict
from app.conversation.interfaces import IIntentResolver
from app.conversation.models import TrackedEntity

class IntentResolver(IIntentResolver):
    def resolve(self, text: str, references: Dict[str, TrackedEntity]) -> str:
        resolved_text = text
        for ref, entity in references.items():
            resolved_text = resolved_text.replace(ref, entity.name)
        return resolved_text
