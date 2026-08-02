import time
from app.result_processing.interfaces import IProcessor, IMetadataExtractor, IChunkReader
from app.execution.models import ExecutionResult
from app.result_processing.models import ProcessedResult, ResultProcessingConfig, StreamMetadata, PaginationMetadata, ProcessingMetrics
from app.result_processing.memory_manager import MemoryManager

class Processor(IProcessor):
    def __init__(self, metadata_extractor: IMetadataExtractor, chunk_reader: IChunkReader):
        self.metadata_extractor = metadata_extractor
        self.chunk_reader = chunk_reader

    def process(self, execution_result: ExecutionResult, config: ResultProcessingConfig) -> ProcessedResult:
        schema = self.metadata_extractor.extract(execution_result)
        memory_manager = MemoryManager(config.max_memory_mb)
        
        start_time = time.time()
        
        chunks = self.chunk_reader.read_chunks(execution_result, config.chunk_size)
        
        metrics = ProcessingMetrics()
        current_bytes = 0
        all_rows = []
        
        for chunk in chunks:
            chunk_start_time = time.time()
            metrics.chunks_processed += 1
            metrics.rows_processed += len(chunk)
            
            chunk_bytes = sum(len(str(v)) for row in chunk for v in row.values())
            current_bytes = memory_manager.check_memory_limit(chunk, current_bytes=current_bytes)
            
            metrics.bytes_processed += chunk_bytes
            metrics.current_buffer_size = current_bytes
            
            if current_bytes / (1024 * 1024) > metrics.peak_memory_mb:
                metrics.peak_memory_mb = current_bytes / (1024 * 1024)
                
            metrics.chunk_latency_ms = (time.time() - chunk_start_time) * 1000
            all_rows.extend(chunk)
            
        metrics.processing_time = time.time() - start_time
        
        return ProcessedResult(
            execution_id=execution_result.execution_id,
            schema_def=schema,
            rows=all_rows,
            pagination=PaginationMetadata(has_next=False, total_rows=metrics.rows_processed),
            streaming=StreamMetadata(is_streaming=False),
            processing_metrics=metrics
        )
