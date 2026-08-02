from typing import List
from app.query_understanding.interfaces import IMetricDetector
from app.query_understanding.models import QueryEntities
from app.database.discovery.models import DatabaseMetadata
from app.database.intelligence.models import SchemaIntelligence

class DeterministicMetricDetector(IMetricDetector):
    def detect(self, entities: QueryEntities, metadata: DatabaseMetadata, intelligence: SchemaIntelligence) -> List[str]:
        metrics = []
        metric_keywords = ["revenue", "sales", "price", "amount", "quantity", "score", "age", "total", "sum", "avg"]
        
        # Check matched columns to see if they are numeric/metrics
        for col in entities.columns:
            if any(k in col.lower() for k in metric_keywords):
                metrics.append(col)
                
        # If no metrics found in exact columns, we could check the intelligence graph, 
        # but deterministically we just rely on keywords for now.
        return list(set(metrics))
