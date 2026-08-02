import time
from app.context_builder.models import StructuredContext
from app.ai_reasoning.interfaces import (
    IReasoningEngine, IAnswerGenerator, IReasoningTraceBuilder,
    IHallucinationGuard, IResponseValidator, ICitationBuilder,
    IConfidenceEngine, IRecommendationEngine, IFollowupGenerator,
    IExplanationEngine, IProviderRouter
)
from app.ai_reasoning.models import AIResponse, AIReasoningRequest, LLMResponse

class ReasoningEngine(IReasoningEngine):
    def __init__(
        self,
        provider_router: IProviderRouter,
        answer_generator: IAnswerGenerator,
        trace_builder: IReasoningTraceBuilder,
        guard: IHallucinationGuard,
        validator: IResponseValidator,
        citation_builder: ICitationBuilder,
        confidence_engine: IConfidenceEngine,
        recommendation_engine: IRecommendationEngine,
        followup_generator: IFollowupGenerator,
        explanation_engine: IExplanationEngine
    ):
        self.provider_router = provider_router
        self.answer_generator = answer_generator
        self.trace_builder = trace_builder
        self.guard = guard
        self.validator = validator
        self.citation_builder = citation_builder
        self.confidence_engine = confidence_engine
        self.recommendation_engine = recommendation_engine
        self.followup_generator = followup_generator
        self.explanation_engine = explanation_engine

    def reason(self, request: AIReasoningRequest, context: StructuredContext) -> AIResponse:
        start_time = time.time()
        
        # 1. Route to provider
        provider = self.provider_router.get_provider(request.provider)
        
        # 2. Generate initial answer (without raw DB access)
        response = self.answer_generator.generate(request.question, context, provider)
        
        # We construct a mock LLMResponse here just to satisfy the trace_builder signature cleanly
        # In a real impl, answer_generator might return (response, raw_llm_resp)
        llm_resp = LLMResponse(text=response.answer, tokens_used=response.response_metadata.tokens_used, model=response.response_metadata.provider_used)
        
        # 3. Build trace
        response.reasoning_trace = self.trace_builder.build(llm_resp, context)
        
        # 4. Guard & Validation
        guard_failures = self.guard.validate(response.answer, context)
        response.warnings.extend(guard_failures)
        
        # 5. Build citations
        response.citations = self.citation_builder.build(response.answer, context)
        
        # 6. Confidence
        response.confidence = self.confidence_engine.compute(context, response.reasoning_trace, guard_failures)
        
        # 7. Add recommendations & followups
        response.recommendations = self.recommendation_engine.generate(response.answer, context)
        response.followup_questions = self.followup_generator.generate(response.answer, context)
        
        # 8. Explanation / Summary
        response.summary = self.explanation_engine.explain(response.answer)
        
        # 9. Final Validation
        self.validator.validate(response)
        
        response.response_metadata.processing_time_ms = (time.time() - start_time) * 1000
        
        return response
