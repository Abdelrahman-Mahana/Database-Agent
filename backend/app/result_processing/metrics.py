import structlog

logger = structlog.get_logger(__name__)

class MetricsLogger:
    def log_metrics(self, result: 'ProcessedResult'):
        m = result.processing_metrics
        logger.info("result_processing_metrics",
                    result_id=result.result_id,
                    rows_processed=m.rows_processed,
                    bytes_processed=m.bytes_processed,
                    processing_time=m.processing_time,
                    peak_memory_mb=m.peak_memory_mb)
