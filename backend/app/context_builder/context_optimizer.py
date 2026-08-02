from app.context_builder.interfaces import IContextOptimizer, IRankingEngine, ITokenEstimator, ICompressor
from app.context_builder.models import StructuredContext, ContextBuildRequest

class ContextOptimizer(IContextOptimizer):
    def __init__(
        self,
        ranking_engine: IRankingEngine,
        token_estimator: ITokenEstimator,
        compressor: ICompressor
    ):
        self.ranking_engine = ranking_engine
        self.token_estimator = token_estimator
        self.compressor = compressor

    def optimize(self, request: ContextBuildRequest, context: StructuredContext) -> None:
        self.ranking_engine.rank(request, context)
        metrics = self.compressor.compress(context)
        context.compression_ratio = metrics.compression_ratio
        context.estimated_tokens = self.token_estimator.estimate(context)
