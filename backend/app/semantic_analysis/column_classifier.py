from typing import List, Any
from app.result_processing.models import ColumnMetadata, GenericDataType
from app.semantic_analysis.interfaces import IColumnClassifier
from app.semantic_analysis.models import SemanticClass

class ColumnClassifier(IColumnClassifier):
    def classify(self, column: ColumnMetadata, values: List[Any]) -> SemanticClass:
        # Fast exit based on predefined type
        if column.type in (GenericDataType.INTEGER, GenericDataType.FLOAT, GenericDataType.DECIMAL):
            # Check if it might be an identifier
            if column.name.lower() in ("id", "uuid") or column.name.lower().endswith("_id"):
                return SemanticClass.IDENTIFIER
            return SemanticClass.NUMERIC
            
        if column.type == GenericDataType.BOOLEAN:
            return SemanticClass.BOOLEAN
            
        if column.type in (GenericDataType.DATE, GenericDataType.DATETIME, GenericDataType.TIMESTAMP):
            return SemanticClass.TEMPORAL
            
        if column.type == GenericDataType.UUID:
            return SemanticClass.IDENTIFIER
            
        if column.type == GenericDataType.JSON:
            return SemanticClass.JSON
            
        if column.type == GenericDataType.ARRAY:
            return SemanticClass.ARRAY
            
        if column.type == GenericDataType.BINARY:
            return SemanticClass.BINARY

        if column.type == GenericDataType.STRING:
            if column.name.lower() in ("id", "uuid") or column.name.lower().endswith("_id"):
                return SemanticClass.IDENTIFIER
                
            non_null_values = [v for v in values if v is not None]
            if not non_null_values:
                return SemanticClass.UNKNOWN
                
            # Heuristic for CATEGORICAL vs TEXT
            unique_count = len(set(non_null_values))
            if unique_count <= 50 or unique_count / len(non_null_values) < 0.1:
                return SemanticClass.CATEGORICAL
            return SemanticClass.TEXT

        return SemanticClass.UNKNOWN
