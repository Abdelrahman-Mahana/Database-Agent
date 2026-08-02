from fastapi import responses
import structlog
from typing import Generator
from app.execution.service import ExecutionService
from app.result_processing.interfaces import IProcessor, IStreamProcessor, ISerializer
from app.result_processing.models import ProcessedResult, ResultProcessingConfig
from app.result_processing.cache import ResultCache
from app.result_processing.metrics import MetricsLogger

logger = structlog.get_logger(__name__)

class ResultProcessingService:
    def __init__(
        self,
        execution_service: ExecutionService,
        processor: IProcessor,
        stream_processor: IStreamProcessor,
        serializer: ISerializer,
        cache: ResultCache,
        metrics_logger: MetricsLogger
    ):
        self.execution_service = execution_service
        self.processor = processor
        self.stream_processor = stream_processor
        self.serializer = serializer
        self.cache = cache
        self.metrics_logger = metrics_logger

    def process_result(self, execution_id: str, config: ResultProcessingConfig) -> ProcessedResult:
        logger.info("Processing execution result", execution_id=execution_id)
        
        exec_result = self.execution_service.get_execution_status(execution_id)
        if not exec_result:
            raise ValueError(f"Execution {execution_id} not found.")
            
        processed_result = self.processor.process(exec_result, config)
        
        self.cache.set(processed_result.result_id, processed_result)
        self.metrics_logger.log_metrics(processed_result)
        
        return processed_result

    def stream_result(self, execution_id: str, config: ResultProcessingConfig) -> Generator[str, None, None]:
        logger.info("Streaming execution result", execution_id=execution_id)
        
        exec_result = self.execution_service.get_execution_status(execution_id)
        if not exec_result:
            raise ValueError(f"Execution {execution_id} not found.")
            
        config.streaming = True
        stream = self.stream_processor.process_stream(exec_result, config)
        
        for chunk in stream:
            yield self.serializer.serialize_json(chunk) + "\n"

    def get_processed_result(self, result_id: str) -> ProcessedResult:
        result = self.cache.get(result_id)
        if not result:
            raise ValueError(f"Processed result {result_id} not found.")
        return result
