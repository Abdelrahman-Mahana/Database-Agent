from app.database.discovery.models import ColumnMetadata
from app.database.profiling.models import ColumnProfile, CategoricalStatistics
from app.database.profiling.profilers.base import IColumnProfiler

class CategoricalProfiler(IColumnProfiler):
    def process(self, column: ColumnMetadata, stats: dict, top_values: dict = None) -> ColumnProfile:
        profile = ColumnProfile(column_name=column.name, data_type=column.data_type, nullable=column.nullable)
        
        total = stats.get("total", 0)
        if total > 0:
            profile.distinct_count = stats.get("distinct_count", 0)
            profile.null_ratio = stats.get("null_count", 0) / total
            profile.unique_ratio = profile.distinct_count / total
            
            if top_values:
                profile.categorical_stats = CategoricalStatistics(
                    top_values=list(top_values.keys()),
                    frequencies=top_values
                )
        return profile
