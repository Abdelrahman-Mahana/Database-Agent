from app.database.profiling.profilers.base import IColumnProfiler
from app.database.discovery.models import ColumnMetadata

class ProfilerFactory:
    def __init__(
        self,
        numeric_profiler: IColumnProfiler,
        categorical_profiler: IColumnProfiler,
        text_profiler: IColumnProfiler,
        datetime_profiler: IColumnProfiler
    ):
        self.numeric_profiler = numeric_profiler
        self.categorical_profiler = categorical_profiler
        self.text_profiler = text_profiler
        self.datetime_profiler = datetime_profiler

    def get_profiler_for_column(self, column: ColumnMetadata) -> IColumnProfiler:
        dt = column.data_type.lower()
        
        if any(t in dt for t in ['int', 'float', 'double', 'numeric', 'decimal', 'real']):
            return self.numeric_profiler
        elif any(t in dt for t in ['date', 'time', 'timestamp']):
            return self.datetime_profiler
        elif any(t in dt for t in ['char', 'text', 'string']):
            if "varchar" in dt or "char" in dt:
                return self.categorical_profiler
            return self.text_profiler
        elif "bool" in dt:
            return self.categorical_profiler
            
        return self.categorical_profiler
