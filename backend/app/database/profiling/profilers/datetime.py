from app.database.discovery.models import ColumnMetadata
from app.database.profiling.models import ColumnProfile, DatetimeStatistics
from app.database.profiling.profilers.base import IColumnProfiler
from datetime import datetime

class DatetimeProfiler(IColumnProfiler):
    def process(self, column: ColumnMetadata, stats: dict, top_values: dict = None) -> ColumnProfile:
        profile = ColumnProfile(column_name=column.name, data_type=column.data_type, nullable=column.nullable)
        
        total = stats.get("total", 0)
        if total > 0:
            profile.distinct_count = stats.get("distinct_count", 0)
            profile.null_ratio = stats.get("null_count", 0) / total
            profile.unique_ratio = profile.distinct_count / total
            
            min_v = stats.get("min_val")
            max_v = stats.get("max_val")
            
            profile.datetime_stats = DatetimeStatistics(
                earliest=min_v if isinstance(min_v, datetime) else None,
                latest=max_v if isinstance(max_v, datetime) else None
            )
        return profile
