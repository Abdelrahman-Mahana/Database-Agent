from app.database.discovery.models import ColumnMetadata
from app.database.profiling.models import ColumnProfile, TextStatistics
from app.database.profiling.profilers.base import IColumnProfiler

class TextProfiler(IColumnProfiler):
    def process(self, column: ColumnMetadata, stats: dict, top_values: dict = None) -> ColumnProfile:
        profile = ColumnProfile(column_name=column.name, data_type=column.data_type, nullable=column.nullable)
        
        total = stats.get("total", 0)
        if total > 0:
            profile.distinct_count = stats.get("distinct_count", 0)
            profile.null_ratio = stats.get("null_count", 0) / total
            profile.unique_ratio = profile.distinct_count / total
            
            profile.text_stats = TextStatistics(
                average_length=stats.get("avg_len"),
                max_length=stats.get("max_len"),
                min_length=stats.get("min_len")
            )
        return profile
