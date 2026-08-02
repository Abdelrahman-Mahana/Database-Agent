from app.dialect.models import DialectLimit
from app.sql_renderer.parameter_builder import ParameterBuilder

class LimitRenderer:
    def render(self, limit_obj: DialectLimit, param_builder: ParameterBuilder) -> str:
        if not limit_obj:
            return ""
            
        # Parameterize limit values to avoid injection
        limit_param = param_builder.add_parameter(limit_obj.limit)
        
        offset_sql = ""
        if limit_obj.offset > 0:
            offset_param = param_builder.add_parameter(limit_obj.offset)
            offset_sql = f" OFFSET {offset_param}"
            
        return f"LIMIT {limit_param}{offset_sql}"
