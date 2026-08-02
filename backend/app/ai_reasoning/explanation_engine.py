from app.ai_reasoning.interfaces import IExplanationEngine

class ExplanationEngine(IExplanationEngine):
    def explain(self, text: str) -> str:
        # Generate summary of the answer text
        return f"Summary of finding: {text[:50]}..."
