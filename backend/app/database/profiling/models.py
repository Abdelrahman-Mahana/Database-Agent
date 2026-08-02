from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime

class NumericStatistics(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None
    mean: Optional[float] = None
    median: Optional[float] = None
    std: Optional[float] = None
    variance: Optional[float] = None
    q1: Optional[float] = None
    q3: Optional[float] = None
    iqr: Optional[float] = None

class CategoricalStatistics(BaseModel):
    top_values: List[str] = Field(default_factory=list)
    frequencies: Dict[str, int] = Field(default_factory=dict)

class TextStatistics(BaseModel):
    average_length: Optional[float] = None
    max_length: Optional[int] = None
    min_length: Optional[int] = None

class DatetimeStatistics(BaseModel):
    earliest: Optional[datetime] = None
    latest: Optional[datetime] = None

class ColumnProfile(BaseModel):
    column_name: str
    data_type: str
    nullable: bool = True
    unique_ratio: float = 0.0
    null_ratio: float = 0.0
    distinct_count: int = 0
    duplicates: Optional[int] = None
    entropy: Optional[float] = None
    
    numeric_stats: Optional[NumericStatistics] = None
    categorical_stats: Optional[CategoricalStatistics] = None
    text_stats: Optional[TextStatistics] = None
    datetime_stats: Optional[DatetimeStatistics] = None

class TableProfile(BaseModel):
    table_name: str
    total_rows: int = 0
    estimated_rows: Optional[int] = None
    total_columns: int = 0
    table_size_bytes: Optional[int] = None
    last_updated: Optional[str] = None
    columns: List[ColumnProfile] = Field(default_factory=list)

class DatabaseProfile(BaseModel):
    profile_id: str
    database_name: str
    schema_hash: str
    profiling_duration: float
    sample_strategy: str
    generated_at: datetime
    tables: List[TableProfile] = Field(default_factory=list)
