from app.logical_query.models import (
    LogicalRelation, LogicalJoin, LogicalProjection, LogicalFilter, LogicalExpression,
    ExpressionType, LogicalColumn, LogicalLiteral, LogicalFunction
)
from app.dialect.models import (
    DialectRelation, DialectJoin, DialectProjection, DialectFilter, DialectExpression,
    DialectIdentifier, DialectLiteral, DialectFunction, DialectOperator, DialectAlias
)
from app.dialect.interfaces import IDialectTranslator

class BaseDialectTranslator(IDialectTranslator):
    def __init__(self, name: str, quote_char: str = '"'):
        self._name = name
        self.quote_char = quote_char
        
    @property
    def dialect_name(self) -> str:
        return self._name
        
    def translate_identifier(self, name: str) -> DialectIdentifier:
        return DialectIdentifier(name=name, quote_char=self.quote_char)
        
    def translate_literal(self, value: any) -> DialectLiteral:
        return DialectLiteral(value=value, type_name=type(value).__name__)
        
    def translate_function(self, func: LogicalExpression) -> DialectFunction:
        func_name = self.map_function(getattr(func, "function_name", "UNKNOWN"))
        args = [self.translate_expression(c) for c in func.children]
        return DialectFunction(name=func_name, args=args)
        
    def translate_relation(self, relation: LogicalRelation) -> DialectRelation:
        ident = self.translate_identifier(relation.table_name)
        alias_ident = self.translate_identifier(relation.alias) if getattr(relation, "alias", None) else None
        return DialectRelation(name=ident, alias=alias_ident)
        
    def translate_join(self, join: LogicalJoin) -> DialectJoin:
        if isinstance(join.left_relation, LogicalJoin):
            left = self.translate_join(join.left_relation)
        else:
            left = self.translate_relation(join.left_relation)
            
        right = self.translate_relation(join.right_relation)
        cond = self.translate_expression(join.condition) if join.condition else None
        
        return DialectJoin(
            join_type=join.join_type.value if hasattr(join.join_type, "value") else str(join.join_type),
            left=left,
            right=right,
            condition=cond
        )
        
    def translate_projection(self, projection: LogicalProjection) -> DialectProjection:
        dp = DialectProjection()
        for expr in projection.expressions:
            if hasattr(expr, "alias") and expr.alias:
                t_expr = self.translate_expression(expr.expression)
                t_alias = self.translate_identifier(expr.alias)
                dp.expressions.append(DialectAlias(expression=t_expr, alias=t_alias))
            else:
                dp.expressions.append(self.translate_expression(expr))
        return dp
        
    def translate_filter(self, filter_obj: LogicalFilter) -> DialectFilter:
        return DialectFilter(condition=self.translate_expression(filter_obj.condition))
        
    def translate_expression(self, expr: LogicalExpression) -> DialectExpression:
        if expr.expr_type == ExpressionType.COLUMN:
            return self.translate_identifier(getattr(expr, "column_name", ""))
        elif expr.expr_type == ExpressionType.LITERAL:
            return self.translate_literal(expr.value)
        elif expr.expr_type == ExpressionType.FUNCTION:
            return self.translate_function(expr)
            
        op_name = str(expr.expr_type.value) if hasattr(expr.expr_type, "value") else str(expr.expr_type)
        operator = DialectOperator(operator=op_name)
        if expr.children:
            operator.children = [self.translate_expression(c) for c in expr.children]
            if len(operator.children) == 2:
                operator.left = operator.children[0]
                operator.right = operator.children[1]
                
        return operator

    def map_function(self, logical_function: str) -> str:
        return logical_function.upper()
        
    def map_type(self, logical_type: str) -> str:
        return logical_type.upper()
