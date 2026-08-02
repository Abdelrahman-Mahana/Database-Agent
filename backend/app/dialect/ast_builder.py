from app.logical_query.models import LogicalQuery
from app.dialect.models import (
    DialectQuery, DialectLimit
)
from app.dialect.interfaces import IAstBuilder, IDialectTranslator

class DeterministicAstBuilder(IAstBuilder):
    def build_ast(self, query: LogicalQuery, translator: IDialectTranslator) -> DialectQuery:
        ast = DialectQuery(
            logical_query_id=query.query_id,
            dialect_name=translator.dialect_name,
            estimated_complexity=query.estimated_complexity,
            confidence=query.confidence
        )
        
        # Relations
        if query.relations:
            ast.relations = [translator.translate_relation(r) for r in query.relations]
            
        # Joins
        if query.joins:
            ast.joins = [translator.translate_join(j) for j in query.joins]
            
        # Projections
        if query.projections:
            ast.projections = translator.translate_projection(query.projections)
                
        # Filters
        if query.filters:
            ast.filters = translator.translate_filter(query.filters)
            
        # Limit
        if query.limit:
            ast.limit = DialectLimit(limit=query.limit.limit, offset=query.limit.offset)
            
        return ast
