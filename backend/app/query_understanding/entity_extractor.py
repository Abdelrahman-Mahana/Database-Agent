import re
from app.query_understanding.interfaces import IEntityExtractor
from app.query_understanding.models import QueryEntities
from app.database.discovery.models import DatabaseMetadata

class KeywordEntityExtractor(IEntityExtractor):
    def extract(self, normalized_query: str, metadata: DatabaseMetadata) -> QueryEntities:
        entities = QueryEntities()
        
        # Simple extraction by matching schema names
        for schema in metadata.schemas:
            for table in schema.tables:
                if table.name.lower() in normalized_query:
                    entities.tables.append(table.name)
                for col in table.columns:
                    if col.name.lower() in normalized_query:
                        entities.columns.append(col.name)
                        
        # Extract time expressions deterministically
        time_keywords = [
            "today", "yesterday", "last week", "last month", "last quarter", "last year",
            "this month", "this year"
        ]
        for tk in time_keywords:
            if tk in normalized_query:
                entities.time_expressions.append(tk)
                
        # Basic business term heuristic (capitalized words in original query if passed, but we get normalized.
        # So we skip business terms in this deterministic fallback)
        
        # De-duplicate
        entities.tables = list(set(entities.tables))
        entities.columns = list(set(entities.columns))
        entities.time_expressions = list(set(entities.time_expressions))
        
        return entities
