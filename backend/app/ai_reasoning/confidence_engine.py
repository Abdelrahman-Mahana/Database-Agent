from typing import List
from app.context_builder.models import StructuredContext
from app.ai_reasoning.interfaces import IConfidenceEngine
from app.ai_reasoning.models import ReasoningTrace

class ConfidenceEngine(IConfidenceEngine):
    def compute(self, context: StructuredContext, trace: ReasoningTrace, guard_failures: List[str]) -> float:
        # Context confidence (from Context Builder)
        ctx_conf = context.confidence
        
        # Semantic confidence (based on data completeness)
        completeness = context.semantic_context.quality_metrics.get("completeness", 1.0)
        sem_conf = max(0.0, min(1.0, float(completeness)))
        
        # Validation confidence (penalize for guard failures)
        val_conf = max(0.0, 1.0 - (0.2 * len(guard_failures)))
        
        # Reasoning confidence (from trace)
        r_conf = 1.0
        if trace.confidence_sources:
            r_conf = sum(trace.confidence_sources.values()) / len(trace.confidence_sources)
            
        # Explainable combination
        final_conf = (ctx_conf * 0.3) + (sem_conf * 0.3) + (val_conf * 0.2) + (r_conf * 0.2)
        
        return max(0.0, min(1.0, final_conf))
