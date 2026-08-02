from app.context_builder.models import StructuredContext
from app.ai_reasoning.interfaces import IReasoningTraceBuilder
from app.ai_reasoning.models import LLMResponse, ReasoningTrace

class ReasoningTraceBuilder(IReasoningTraceBuilder):
    def build(self, llm_response: LLMResponse, context: StructuredContext) -> ReasoningTrace:
        trace = ReasoningTrace()
        # Do not expose chain-of-thought, extract only rules and evidence deterministically
        trace.evidence_used = [t.name for t in context.schema_context.tables.values()]
        trace.rules_applied = ["context_isolation_rule", "deterministic_aggregation_rule"]
        trace.confidence_sources = {
            "semantic_consistency": 1.0,
            "data_completeness": context.semantic_context.dataset_profile.get("overall_completeness", 1.0)
        }
        return trace
