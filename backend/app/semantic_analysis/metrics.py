import structlog
from app.semantic_analysis.models import SemanticAnalysisResult

logger = structlog.get_logger(__name__)

class SemanticMetricsCollector:
    def log_analysis(self, result: SemanticAnalysisResult):
        logger.info(
            "semantic_analysis_metrics",
            analysis_id=result.analysis_id,
            result_id=result.result_id,
            processing_time_ms=result.analysis_metrics.processing_time_ms,
            column_count=result.dataset_profile.column_count,
            row_count=result.dataset_profile.row_count
        )
