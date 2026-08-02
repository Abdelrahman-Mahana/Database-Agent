from typing import List
from app.context_builder.models import StructuredContext
from app.ai_reasoning.interfaces import ICitationBuilder
from app.ai_reasoning.models import Citation

class CitationBuilder(ICitationBuilder):
    def build(self, answer: str, context: StructuredContext) -> List[Citation]:
        citations = []
        answer_lower = answer.lower()
        
        # Document table references
        for t_name, t_data in context.schema_context.tables.items():
            if t_name.lower() in answer_lower:
                citations.append(Citation(
                    claim=f"Referenced entity: {t_name}",
                    context_section=f"schema_context.tables.{t_name}",
                    relevance_score=t_data.relevance_score
                ))
                
        # Document business term usage
        for term in context.business_terms:
            if term.lower() in answer_lower:
                 citations.append(Citation(
                    claim=f"Applied business term: {term}",
                    context_section="business_terms",
                    relevance_score=1.0
                ))
                
        return citations
