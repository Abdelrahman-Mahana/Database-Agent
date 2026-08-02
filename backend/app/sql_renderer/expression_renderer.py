from typing import List
from app.dialect.models import (
    DialectExpression, DialectIdentifier, DialectLiteral, DialectFunction, 
    DialectOperator, DialectAlias
)
from app.sql_renderer.parameter_builder import ParameterBuilder
from app.sql_renderer.identifier_renderer import IdentifierRenderer

class ExpressionRenderer:
    def __init__(self, ident_renderer: IdentifierRenderer):
        self.ident_renderer = ident_renderer

    def render(self, expr: DialectExpression, param_builder: ParameterBuilder) -> str:
        if isinstance(expr, DialectIdentifier):
            return self.ident_renderer.render(expr)
            
        elif isinstance(expr, DialectLiteral):
            # Parameterize literals!
            return param_builder.add_parameter(expr.value)
            
        elif isinstance(expr, DialectFunction):
            args = [self.render(arg, param_builder) for arg in expr.args]
            return f"{expr.name}({', '.join(args)})"
            
        elif isinstance(expr, DialectOperator):
            op = expr.operator.upper()
            
            # Map logical generic ops to SQL standard if needed
            op_map = {
                "EQUALS": "=",
                "NOT_EQUALS": "<>",
                "GREATER_THAN": ">",
                "LESS_THAN": "<",
                "GREATER_THAN_OR_EQUALS": ">=",
                "LESS_THAN_OR_EQUALS": "<=",
                "AND": "AND",
                "OR": "OR",
                "IN": "IN",
                "NOT_IN": "NOT IN",
                "IS_NULL": "IS NULL",
                "IS_NOT_NULL": "IS NOT NULL"
            }
            sql_op = op_map.get(op, op)
            
            if expr.children:
                if op in ["AND", "OR"]:
                    rendered_children = [self.render(c, param_builder) for c in expr.children]
                    return f"({f' {sql_op} '.join(rendered_children)})"
            
            if getattr(expr, "left", None) and getattr(expr, "right", None):
                left_r = self.render(expr.left, param_builder)
                right_r = self.render(expr.right, param_builder)
                return f"({left_r} {sql_op} {right_r})"
                
            if getattr(expr, "left", None) and not getattr(expr, "right", None):
                # Unary ops like IS NULL
                left_r = self.render(expr.left, param_builder)
                return f"({left_r} {sql_op})"
                
            return ""
            
        elif isinstance(expr, DialectAlias):
            base_expr = self.render(expr.expression, param_builder)
            alias = self.ident_renderer.render(expr.alias)
            return f"{base_expr} AS {alias}"
            
        return ""
