from typing import List
from app.context_builder.models import StructuredContext
from app.ai_reasoning.interfaces import IFollowupGenerator

class FollowupGenerator(IFollowupGenerator):
    def generate(self, answer: str, context: StructuredContext) -> List[str]:
        # Generate analytical follow-ups
        return [
            "Would you like a deeper breakdown of the underlying statistical distribution?",
            "Should I analyze the candidate foreign key relationships identified?"
        ]
