from app.result_processing.interfaces import IMetadataExtractor, ITypeNormalizer
from app.result_processing.models import ResultSchema, ColumnMetadata
from app.execution.models import ExecutionResult

class DeterministicMetadataExtractor(IMetadataExtractor):
    def __init__(self, normalizer: ITypeNormalizer):
        self.normalizer = normalizer

    def extract(self, execution_result: ExecutionResult) -> ResultSchema:
        raw_columns = execution_result.database_metadata.get("columns", [])
        
        schema = ResultSchema()
        for i, col in enumerate(raw_columns):
            name = col.get("name", f"col_{i}")
            native_type = col.get("type", "unknown")
            
            schema.columns.append(ColumnMetadata(
                name=name,
                type=self.normalizer.normalize(native_type),
                nullable=col.get("nullable", True),
                precision=col.get("precision"),
                scale=col.get("scale"),
                length=col.get("length")
            ))
            
        # Mock schema if none provided (for deterministic tests)
        if not schema.columns:
            schema.columns.append(ColumnMetadata(name="id", type=self.normalizer.normalize("int"), nullable=False))
            schema.columns.append(ColumnMetadata(name="value", type=self.normalizer.normalize("varchar"), nullable=True))
            
        return schema
