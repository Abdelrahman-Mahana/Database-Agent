from typing import List
from app.dialect.models import DialectJoin, DialectRelation
from app.sql_renderer.parameter_builder import ParameterBuilder
from app.sql_renderer.expression_renderer import ExpressionRenderer
from app.sql_renderer.identifier_renderer import IdentifierRenderer

class JoinRenderer:
    def __init__(self, expr_renderer: ExpressionRenderer, ident_renderer: IdentifierRenderer):
        self.expr_renderer = expr_renderer
        self.ident_renderer = ident_renderer
        
    def render_relation(self, relation: DialectRelation) -> str:
        name = self.ident_renderer.render(relation.name)
        if relation.alias:
            alias = self.ident_renderer.render(relation.alias)
            return f"{name} {alias}"
        return name

    def render(self, joins: List[DialectJoin], param_builder: ParameterBuilder) -> str:
        if not joins:
            return ""
            
        parts = []
        for join in joins:
            join_type = join.join_type.upper()
            
            # Left could be another join or relation. For simplicity in deterministic AST:
            # We assume the FROM clause starts with the leftmost relation
            if isinstance(join.left, DialectRelation):
                # Only need the very first FROM table if we are starting
                if not parts:
                    parts.append(f"FROM {self.render_relation(join.left)}")
            elif isinstance(join.left, DialectJoin):
                # The recursive structure might mean we've already handled the left,
                # but typically ASTs flat map the joins or build them linearly.
                pass
                
            right_table = self.render_relation(join.right)
            
            cond = ""
            if join.condition:
                cond = f" ON {self.expr_renderer.render(join.condition, param_builder)}"
                
            parts.append(f"{join_type} JOIN {right_table}{cond}")
            
        return "\n".join(parts)
