from app.dialect.models import DialectFilter
from app.sql_renderer.parameter_builder import ParameterBuilder
from app.sql_renderer.expression_renderer import ExpressionRenderer

class FilterRenderer:
    def __init__(self, expr_renderer: ExpressionRenderer):
        self.expr_renderer = expr_renderer
        
    def render(self, filter_obj: DialectFilter, param_builder: ParameterBuilder) -> str:
        if not filter_obj or not filter_obj.condition:
            return ""
            
        return f"WHERE {self.expr_renderer.render(filter_obj.condition, param_builder)}"
