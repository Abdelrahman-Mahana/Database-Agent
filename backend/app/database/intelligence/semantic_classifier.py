from app.database.discovery.models import ColumnMetadata
from app.database.intelligence.interfaces import ISemanticClassifier
from app.database.intelligence.models import ColumnSemantic
from app.database.intelligence.utils import normalize_name

class DeterministicSemanticClassifier(ISemanticClassifier):
    def classify_column(self, column: ColumnMetadata) -> ColumnSemantic:
        norm_name = normalize_name(column.name)
        norm_type = normalize_name(column.data_type)
        
        semantic_type = "unknown"
        confidence = 0.0
        reason = "No matching heuristic"
        
        if "email" in norm_name:
            semantic_type = "email"
            confidence = 0.9
            reason = "Column name contains 'email'"
        elif "phone" in norm_name:
            semantic_type = "phone"
            confidence = 0.9
            reason = "Column name contains 'phone'"
        elif "address" in norm_name or "city" in norm_name or "country" in norm_name or "zip" in norm_name:
            semantic_type = "address"
            confidence = 0.8
            reason = "Column name implies geolocation or address"
        elif "price" in norm_name or "amount" in norm_name or "total" in norm_name:
            semantic_type = "currency"
            confidence = 0.8
            reason = "Column name implies monetary value"
        elif "quantity" in norm_name or "qty" in norm_name:
            semantic_type = "quantity"
            confidence = 0.9
            reason = "Column name implies numerical quantity"
        elif "latitude" in norm_name or "longitude" in norm_name or "lat" == norm_name or "lon" == norm_name or "lng" == norm_name:
            semantic_type = "geolocation"
            confidence = 0.9
            reason = "Column name implies coordinates"
        elif "json" in norm_type:
            semantic_type = "json"
            confidence = 1.0
            reason = "Column data type is JSON"
        elif "uuid" in norm_type:
            semantic_type = "uuid"
            confidence = 1.0
            reason = "Column data type is UUID"
        elif norm_name.startswith("is") or norm_name.startswith("has") or "bool" in norm_type:
            semantic_type = "boolean_flag"
            confidence = 0.8
            reason = "Column name implies boolean flag"
        elif "createdat" in norm_name or "updatedat" in norm_name or "deletedat" in norm_name or "date" in norm_name or "time" in norm_type:
            semantic_type = "datetime"
            confidence = 0.9
            reason = "Column name or type implies temporal data"
        elif column.primary_key or norm_name == "id" or norm_name.endswith("id"):
            semantic_type = "identifier"
            confidence = 0.9
            reason = "Column is a primary key or named as identifier"
        elif "status" in norm_name or "state" in norm_name:
            semantic_type = "status"
            confidence = 0.8
            reason = "Column name implies state or status"
        
        return ColumnSemantic(
            column_name=column.name,
            semantic_type=semantic_type,
            confidence=confidence,
            evidence=f"Name: {column.name}, Type: {column.data_type}",
            reason=reason
        )
