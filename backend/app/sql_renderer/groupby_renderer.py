from app.dialect.models import DialectAggregate
from app.sql_renderer.parameter_builder import ParameterBuilder
from app.sql_renderer.expression_renderer import ExpressionRenderer

class GroupByRenderer:
    def __init__(self, expr_renderer: ExpressionRenderer):
        self.expr_renderer = expr_renderer
        
    def render(self, group_obj: DialectAggregate, param_builder: ParameterBuilder) -> str:
        if not group_obj or not group_obj.expressions:
            return ""
            
        parts = []
        for expr in group_obj.expressions:
            parts.append(self.expr_renderer.render(expr, param_builder))
            
        return f"GROUP BY {', '.join(parts)}"
