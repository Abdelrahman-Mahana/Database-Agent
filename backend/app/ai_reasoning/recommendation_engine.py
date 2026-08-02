from typing import List
from app.context_builder.models import StructuredContext
from app.ai_reasoning.interfaces import IRecommendationEngine
from app.ai_reasoning.models import Recommendation

class RecommendationEngine(IRecommendationEngine):
    def generate(self, answer: str, context: StructuredContext) -> List[Recommendation]:
        recs = []
        # Inspect Semantic Quality
        qm = context.semantic_context.quality_metrics
        if qm and qm.get("null_ratio", 0) > 0.3:
            recs.append(Recommendation(
                actionable_insight="High missing values detected in critical dataset.",
                business_impact="May skew predictive models or result in incomplete reports."
            ))
        return recs
