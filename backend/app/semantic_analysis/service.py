import structlog
from app.result_processing.service import ResultProcessingService
from app.semantic_analysis.factory import AnalyzerFactory
from app.semantic_analysis.models import SemanticAnalysisResult
from app.semantic_analysis.cache import SemanticCache
from app.semantic_analysis.metrics import SemanticMetricsCollector

logger = structlog.get_logger(__name__)

class SemanticAnalysisService:
    def __init__(
        self,
        result_processing_service: ResultProcessingService,
        analyzer_factory: AnalyzerFactory,
        cache: SemanticCache,
        metrics: SemanticMetricsCollector
    ):
        self.result_processing_service = result_processing_service
        self.analyzer_factory = analyzer_factory
        self.cache = cache
        self.metrics = metrics

    def run_analysis(self, result_id: str) -> SemanticAnalysisResult:
        logger.info("Running semantic analysis", result_id=result_id)
        
        # 1. Fetch ProcessedResult
        processed_result = self.result_processing_service.get_processed_result(result_id)
        if not processed_result:
            raise ValueError(f"Processed result {result_id} not found.")
            
        # 2. Get Analyzer
        analyzer = self.analyzer_factory.get_analyzer()
        
        # 3. Analyze
        analysis_result = analyzer.analyze(processed_result)
        
        # 4. Cache & Metrics
        self.cache.set(analysis_result.analysis_id, analysis_result)
        self.metrics.log_analysis(analysis_result)
        
        return analysis_result
        
    def get_analysis(self, analysis_id: str) -> SemanticAnalysisResult:
        result = self.cache.get(analysis_id)
        if not result:
            raise ValueError(f"Analysis {analysis_id} not found.")
        return result
