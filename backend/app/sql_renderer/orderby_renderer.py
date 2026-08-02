from app.dialect.models import DialectSort
from app.sql_renderer.parameter_builder import ParameterBuilder
from app.sql_renderer.expression_renderer import ExpressionRenderer
from app.sql_renderer.identifier_renderer import IdentifierRenderer

class OrderByRenderer:
    def __init__(self, expr_renderer: ExpressionRenderer):
        self.expr_renderer = expr_renderer
        
    def render(self, sort_obj: DialectSort, param_builder: ParameterBuilder) -> str:
        if not sort_obj or not sort_obj.orders:
            return ""
            
        parts = []
        for order in sort_obj.orders:
            expr = order.get("expression")
            direction = order.get("direction", "ASC")
            
            # Since expression could be a DialectExpression
            if expr:
                rendered_expr = self.expr_renderer.render(expr, param_builder)
                parts.append(f"{rendered_expr} {direction}")
                
        if not parts:
            return ""
            
        return f"ORDER BY {', '.join(parts)}"
