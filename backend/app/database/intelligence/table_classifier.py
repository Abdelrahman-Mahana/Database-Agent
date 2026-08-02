from app.database.discovery.models import TableMetadata
from app.database.intelligence.interfaces import ITableClassifier
from app.database.intelligence.models import TableClassification
from app.database.intelligence.utils import normalize_name

class DeterministicTableClassifier(ITableClassifier):
    def classify_table(self, table: TableMetadata) -> TableClassification:
        norm_name = normalize_name(table.name)
        role = "reference"
        confidence = 0.5
        reason = "Default role assigned"
        
        fk_count = len([c for c in table.columns if c.foreign_key])
        
        if "log" in norm_name or "history" in norm_name or "audit" in norm_name:
            role = "audit_log"
            confidence = 0.9
            reason = "Table name matches log/audit conventions"
        elif fk_count >= 2 and len(table.columns) <= 5:
            role = "bridge_table"
            confidence = 0.8
            reason = f"High ratio of foreign keys ({fk_count}) to total columns ({len(table.columns)})"
        elif any(k in norm_name for k in ["transaction", "order", "payment", "invoice"]):
            role = "transaction_table"
            confidence = 0.9
            reason = "Table name matches transactional conventions"
        elif "lookup" in norm_name or "type" in norm_name or "status" in norm_name or "category" in norm_name:
            role = "lookup_table"
            confidence = 0.8
            reason = "Table name implies enumeration or lookup"
        elif len(table.columns) > 10 and not any(k in norm_name for k in ["log", "audit"]):
            role = "dimension_table"
            confidence = 0.7
            reason = "Large column count implies dimension properties"
        elif fk_count >= 2:
            role = "fact_table"
            confidence = 0.7
            reason = "Multiple foreign keys implies fact measurements"

        return TableClassification(
            table_name=table.name,
            role=role,
            confidence=confidence,
            evidence=f"Columns: {len(table.columns)}, FKs: {fk_count}",
            reason=reason
        )
