from app.query_understanding.interfaces import IRouter
from app.query_understanding.models import QueryRouting, QueryIntent, QueryEntities

class DeterministicRouter(IRouter):
    def route(self, intent: QueryIntent, entities: QueryEntities) -> QueryRouting:
        if not entities.tables and not entities.columns:
            return QueryRouting.GENERAL_KNOWLEDGE
            
        if intent in [QueryIntent.EXPLAIN, QueryIntent.DESCRIBE, QueryIntent.SUMMARY]:
            return QueryRouting.HYBRID
            
        return QueryRouting.DATABASE_QUERY
