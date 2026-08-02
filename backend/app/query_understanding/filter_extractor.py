from typing import List
from app.query_understanding.interfaces import IFilterExtractor
from app.query_understanding.models import QueryFilter, QueryEntities, FilterOperator
from app.database.discovery.models import DatabaseMetadata

class RegexFilterExtractor(IFilterExtractor):
    def extract(self, normalized_query: str, entities: QueryEntities, metadata: DatabaseMetadata) -> List[QueryFilter]:
        filters = []
        
        # Very simplistic regex extraction for deterministic requirements
        # e.g., "where status equals active", "age greater than 20"
        
        for col in entities.columns:
            # equals
            if f"{col} equals " in normalized_query or f"{col} = " in normalized_query:
                filters.append(QueryFilter(field=col, operator=FilterOperator.EQUALS, value="extracted_val")) # Needs true parsing for value
            # greater than
            if f"{col} greater than " in normalized_query or f"{col} > " in normalized_query:
                filters.append(QueryFilter(field=col, operator=FilterOperator.GREATER_THAN, value="extracted_val"))
            # less than
            if f"{col} less than " in normalized_query or f"{col} < " in normalized_query:
                filters.append(QueryFilter(field=col, operator=FilterOperator.LESS_THAN, value="extracted_val"))
                
        return filters
