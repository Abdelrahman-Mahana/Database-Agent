import time
from typing import Generator
from app.result_processing.interfaces import IStreamProcessor, IMetadataExtractor, IChunkReader
from app.execution.models import ExecutionResult
from app.result_processing.models import ProcessedResult, ResultProcessingConfig, StreamMetadata, PaginationMetadata, ProcessingMetrics
from app.result_processing.memory_manager import MemoryManager

class StreamProcessor(IStreamProcessor):
    def __init__(self, metadata_extractor: IMetadataExtractor, chunk_reader: IChunkReader):
        self.metadata_extractor = metadata_extractor
        self.chunk_reader = chunk_reader

    def process_stream(self, execution_result: ExecutionResult, config: ResultProcessingConfig) -> Generator[ProcessedResult, None, None]:
        schema = self.metadata_extractor.extract(execution_result)
        memory_manager = MemoryManager(config.max_memory_mb)
        
        start_time = time.time()
        
        chunks = self.chunk_reader.read_chunks(execution_result, config.chunk_size)
        
        metrics = ProcessingMetrics()
        current_bytes = 0
        
        for chunk in chunks:
            chunk_start_time = time.time()
            # Enforce streaming: memory should not accumulate across yields
            # The client consumes each ProcessedResult independently.
            metrics.chunks_processed += 1
            metrics.rows_processed += len(chunk)
            
            # Simple simulation of byte calculation
            chunk_bytes = sum(len(str(v)) for row in chunk for v in row.values())
            current_bytes = memory_manager.check_memory_limit(chunk, current_bytes=0) # Reset per chunk for streaming
            
            metrics.bytes_processed += chunk_bytes
            metrics.current_buffer_size = len(chunk)
            
            if current_bytes / (1024 * 1024) > metrics.peak_memory_mb:
                metrics.peak_memory_mb = current_bytes / (1024 * 1024)
                
            metrics.chunk_latency_ms = (time.time() - chunk_start_time) * 1000
            metrics.processing_time = time.time() - start_time
            
            result = ProcessedResult(
                execution_id=execution_result.execution_id,
                schema_def=schema,
                rows=chunk,
                pagination=PaginationMetadata(has_next=True, offset=metrics.rows_processed - len(chunk), limit=config.chunk_size),
                streaming=StreamMetadata(is_streaming=True, chunk_size=config.chunk_size),
                processing_metrics=metrics
            )
            yield result
