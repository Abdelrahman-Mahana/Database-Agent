import json
from app.context_builder.models import StructuredContext
from app.ai_reasoning.interfaces import IPromptBuilder

class PromptBuilder(IPromptBuilder):
    def build(self, question: str, context: StructuredContext) -> str:
        system = "You are a deterministic AI Data Reasoning Engine. Use ONLY the provided context."
        
        # Build highly compressed, strictly semantic context projection
        ctx_dump = {
            "dataset_profile": context.semantic_context.dataset_profile,
            "quality_metrics": context.semantic_context.quality_metrics,
            "relevant_tables": [
                {
                    "name": t.name, 
                    "description": t.description, 
                    "columns": list(t.columns.keys())
                }
                for t in context.schema_context.tables.values()
            ],
            "execution_summary": context.execution_context.model_dump(),
            "business_terms": context.business_terms,
            "entities": context.relevant_entities
        }
        
        prompt = (
            f"{system}\n\n"
            f"=== CONTEXT ===\n"
            f"{json.dumps(ctx_dump, indent=2)}\n\n"
            f"=== WARNINGS ===\n"
            f"{context.warnings}\n\n"
            f"=== QUESTION ===\n"
            f"{question}\n\n"
            f"=== STRICT RULES ===\n"
            f"1. NEVER mention SQL, SELECT, or databases.\n"
            f"2. Validate every claim against the CONTEXT.\n"
            f"3. Provide clear explanations based solely on execution_summary and relevant_tables.\n"
            f"4. If the context does not contain the answer, state that explicitly.\n"
            f"5. STRICT LANGUAGE ALIGNMENT: You MUST respond in the exact same language as the user's question. If the question is in Arabic, your entire response must be in Arabic, naturally matching their dialect. If the question is in English, your response must be in English."
        )
        return prompt
