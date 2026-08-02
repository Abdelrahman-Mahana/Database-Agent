from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from enum import Enum
from datetime import datetime, timezone
import uuid

class GenericDataType(str, Enum):
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    DECIMAL = "DECIMAL"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    DATETIME = "DATETIME"
    TIMESTAMP = "TIMESTAMP"
    UUID = "UUID"
    JSON = "JSON"
    ARRAY = "ARRAY"
    BINARY = "BINARY"
    STRING = "STRING"
    NULL = "NULL"
    UNKNOWN = "UNKNOWN"

class ColumnMetadata(BaseModel):
    name: str
    type: GenericDataType
    nullable: bool = True
    precision: Optional[int] = None
    scale: Optional[int] = None
    length: Optional[int] = None

class ResultSchema(BaseModel):
    columns: List[ColumnMetadata] = Field(default_factory=list)

class PaginationMetadata(BaseModel):
    has_next: bool = False
    next_cursor: Optional[str] = None
    total_rows: Optional[int] = None
    offset: int = 0
    limit: int = 1000

class StreamMetadata(BaseModel):
    is_streaming: bool = False
    chunk_size: int = 1000

class ProcessingMetrics(BaseModel):
    rows_processed: int = 0
    bytes_processed: int = 0
    processing_time: float = 0.0
    chunks_processed: int = 0
    peak_memory_mb: float = 0.0
    current_buffer_size: int = 0
    spilled_to_disk: bool = False
    chunk_latency_ms: float = 0.0

class ProcessedResult(BaseModel):
    result_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    execution_id: str
    schema_def: ResultSchema = Field(default_factory=ResultSchema)
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    statistics: Dict[str, Any] = Field(default_factory=dict)
    pagination: PaginationMetadata = Field(default_factory=PaginationMetadata)
    streaming: StreamMetadata = Field(default_factory=StreamMetadata)
    processing_metrics: ProcessingMetrics = Field(default_factory=ProcessingMetrics)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class ResultProcessingConfig(BaseModel):
    chunk_size: int = 1000
    max_memory_mb: float = 512.0
    streaming: bool = False
