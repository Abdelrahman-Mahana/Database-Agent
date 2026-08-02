from app.dialect.models import DialectProjection
from app.sql_renderer.parameter_builder import ParameterBuilder
from app.sql_renderer.expression_renderer import ExpressionRenderer

class ProjectionRenderer:
    def __init__(self, expr_renderer: ExpressionRenderer):
        self.expr_renderer = expr_renderer
        
    def render(self, proj: DialectProjection, param_builder: ParameterBuilder) -> str:
        if not proj or not proj.expressions:
            return "*"
            
        parts = []
        for expr in proj.expressions:
            parts.append(self.expr_renderer.render(expr, param_builder))
            
        return ", ".join(parts)
