from typing import Generator, List, Dict, Any
from app.result_processing.interfaces import IChunkReader
from app.execution.models import ExecutionResult

class DeterministicChunkReader(IChunkReader):
    def read_chunks(self, execution_result: ExecutionResult, chunk_size: int) -> Generator[List[Dict[str, Any]], None, None]:
        # Simulating chunk reading natively without blowing up memory
        # In a real driver, this is `while True: rows = cursor.fetchmany(chunk_size)`
        rows_to_simulate = execution_result.rows_returned if execution_result.rows_returned > 0 else 100
        
        current = 0
        while current < rows_to_simulate:
            batch_size = min(chunk_size, rows_to_simulate - current)
            chunk = []
            for i in range(batch_size):
                # Deterministic mocked row matching the mocked schema
                chunk.append({"id": current + i, "value": f"mocked_data_{current + i}"})
            yield chunk
            current += batch_size
