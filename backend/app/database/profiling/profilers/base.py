from app.database.discovery.models import ColumnMetadata
from app.database.profiling.models import ColumnProfile

class IColumnProfiler:
    def process(self, column: ColumnMetadata, stats: dict, top_values: dict = None) -> ColumnProfile:
        pass
