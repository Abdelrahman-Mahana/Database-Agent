from app.dialect.interfaces import IDialectOptimizer
from app.dialect.models import (
    DialectQuery, DialectAlias, DialectIdentifier, DialectOperator, DialectLiteral, DialectExpression
)

class DeterministicDialectOptimizer(IDialectOptimizer):
    def optimize(self, query: DialectQuery) -> DialectQuery:
        self._remove_redundant_aliases(query)
        self._normalize_identifiers(query)
        if query.filters:
            query.filters.condition = self._simplify_constant_expressions(query.filters.condition)
        return query
        
    def _remove_redundant_aliases(self, query: DialectQuery):
        if not query.projections or not query.projections.expressions:
            return
            
        new_exprs = []
        for expr in query.projections.expressions:
            if isinstance(expr, DialectAlias) and isinstance(expr.expression, DialectIdentifier):
                if expr.expression.name == expr.alias.name:
                    new_exprs.append(expr.expression)
                    continue
            new_exprs.append(expr)
        query.projections.expressions = new_exprs
        
    def _normalize_identifiers(self, query: DialectQuery):
        for rel in query.relations:
            if rel.name and isinstance(rel.name, DialectIdentifier):
                rel.name.name = rel.name.name.strip()
            if rel.alias and isinstance(rel.alias, DialectIdentifier):
                rel.alias.name = rel.alias.name.strip()
                
        if query.projections and query.projections.expressions:
            for p_expr in query.projections.expressions:
                if isinstance(p_expr, DialectIdentifier):
                    p_expr.name = p_expr.name.strip()
                elif isinstance(p_expr, DialectAlias):
                    p_expr.alias.name = p_expr.alias.name.strip()
                    if isinstance(p_expr.expression, DialectIdentifier):
                        p_expr.expression.name = p_expr.expression.name.strip()
                        
    def _simplify_constant_expressions(self, expr: DialectExpression) -> DialectExpression:
        if isinstance(expr, DialectOperator):
            if getattr(expr, "left", None):
                expr.left = self._simplify_constant_expressions(expr.left)
            if getattr(expr, "right", None):
                expr.right = self._simplify_constant_expressions(expr.right)
            if getattr(expr, "children", None):
                expr.children = [self._simplify_constant_expressions(c) for c in expr.children]
                
            if expr.operator == "AND" and len(expr.children) == 2:
                left_c = expr.children[0]
                right_c = expr.children[1]
                if isinstance(left_c, DialectLiteral) and left_c.value is True:
                    return right_c
                if isinstance(right_c, DialectLiteral) and right_c.value is True:
                    return left_c
                    
        return expr
