import json
from app.context_builder.interfaces import ICompressor
from app.context_builder.models import StructuredContext, OptimizationMetrics

class ContextCompressor(ICompressor):
    def compress(self, context: StructuredContext) -> OptimizationMetrics:
        orig_size = len(json.dumps(context.model_dump(), default=str).encode('utf-8'))
        
        # 1. Semantic Compression: Keep only top ranked tables if schema is too large
        tables = context.schema_context.tables
        if len(tables) > 10:
            top_tables = {k: v for k, v in tables.items() if v.relevance_score > 1.0}
            if not top_tables: 
                top_tables = dict(list(tables.items())[:5])
            context.schema_context.tables = top_tables
            
        # 2. Merge equivalent info and remove redundant metadata
        for t_name, t_data in context.schema_context.tables.items():
            # Reset score to save space if needed, but keeping it helps explainability
            # Prune unused columns if a table has too many (>50) to preserve semantic meaning
            if len(t_data.columns) > 50:
                top_cols = {k: v for k, v in t_data.columns.items() if v.relevance_score > 1.0}
                if not top_cols:
                    top_cols = dict(list(t_data.columns.items())[:20])
                t_data.columns = top_cols

        comp_size = len(json.dumps(context.model_dump(), default=str).encode('utf-8'))
        
        return OptimizationMetrics(
            original_size_bytes=orig_size,
            compressed_size_bytes=comp_size,
            compression_ratio=comp_size / orig_size if orig_size > 0 else 1.0
        )
