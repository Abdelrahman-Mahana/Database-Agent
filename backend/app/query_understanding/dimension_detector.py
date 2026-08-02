from typing import List
from app.query_understanding.interfaces import IDimensionDetector
from app.query_understanding.models import QueryEntities
from app.database.discovery.models import DatabaseMetadata
from app.database.intelligence.models import SchemaIntelligence

class DeterministicDimensionDetector(IDimensionDetector):
    def detect(self, entities: QueryEntities, metadata: DatabaseMetadata, intelligence: SchemaIntelligence) -> List[str]:
        dimensions = []
        dimension_keywords = ["country", "city", "department", "product", "category", "region", "customer", "type", "status", "name"]
        
        for col in entities.columns:
            if any(k in col.lower() for k in dimension_keywords):
                dimensions.append(col)
                
        # Also any string column identified might be a dimension
        return list(set(dimensions))
