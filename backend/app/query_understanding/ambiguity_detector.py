from typing import List
from app.query_understanding.interfaces import IAmbiguityDetector
from app.query_understanding.models import QueryAmbiguity, QueryEntities
from app.database.discovery.models import DatabaseMetadata

class DeterministicAmbiguityDetector(IAmbiguityDetector):
    def detect(self, query: str, entities: QueryEntities, metrics: List[str], dimensions: List[str], metadata: DatabaseMetadata) -> List[QueryAmbiguity]:
        ambiguities = []
        
        if not entities.tables:
            ambiguities.append(QueryAmbiguity(
                issue_type="MISSING_TABLES",
                description="No known tables were detected in the query.",
                candidates=[t.name for s in metadata.schemas for t in s.tables][:5]
            ))
            
        if not metrics and "count" not in query:
            ambiguities.append(QueryAmbiguity(
                issue_type="MISSING_METRICS",
                description="Query asks for data but no measurable metrics were found.",
                candidates=[]
            ))
            
        return ambiguities
