from app.database.discovery.models import ColumnMetadata
from app.database.profiling.models import ColumnProfile, NumericStatistics
from app.database.profiling.profilers.base import IColumnProfiler

class NumericProfiler(IColumnProfiler):
    def process(self, column: ColumnMetadata, stats: dict, top_values: dict = None) -> ColumnProfile:
        profile = ColumnProfile(column_name=column.name, data_type=column.data_type, nullable=column.nullable)
        
        total = stats.get("total", 0)
        if total > 0:
            profile.distinct_count = stats.get("distinct_count", 0)
            profile.null_ratio = stats.get("null_count", 0) / total
            profile.unique_ratio = profile.distinct_count / total
            
            profile.numeric_stats = NumericStatistics(
                min=stats.get("min_val"),
                max=stats.get("max_val"),
                mean=stats.get("mean_val")
            )
        return profile
