from typing import List
from app.sql_renderer.interfaces import ISQLRenderer
from app.dialect.models import (
    DialectQuery, DialectExpression, DialectRelation, DialectJoin, DialectFilter,
    DialectProjection, DialectAggregate, DialectSort, DialectLimit
)
from app.sql_renderer.models import SQLDocument
from app.sql_renderer.parameter_builder import ParameterBuilder
from app.sql_renderer.identifier_renderer import IdentifierRenderer
from app.sql_renderer.expression_renderer import ExpressionRenderer
from app.sql_renderer.projection_renderer import ProjectionRenderer
from app.sql_renderer.join_renderer import JoinRenderer
from app.sql_renderer.filter_renderer import FilterRenderer
from app.sql_renderer.groupby_renderer import GroupByRenderer
from app.sql_renderer.orderby_renderer import OrderByRenderer
from app.sql_renderer.limit_renderer import LimitRenderer
from app.sql_renderer.formatter import SQLFormatter
from app.sql_renderer.utils import determine_param_style

class DeterministicBaseRenderer(ISQLRenderer):
    def __init__(
        self,
        dialect_name: str,
        ident_renderer: IdentifierRenderer,
        expr_renderer: ExpressionRenderer,
        proj_renderer: ProjectionRenderer,
        join_renderer: JoinRenderer,
        filter_renderer: FilterRenderer,
        group_renderer: GroupByRenderer,
        order_renderer: OrderByRenderer,
        limit_renderer: LimitRenderer,
        formatter: SQLFormatter
    ):
        self._dialect_name = dialect_name
        self.ident_renderer = ident_renderer
        self.expr_renderer = expr_renderer
        self.proj_renderer = proj_renderer
        self.join_renderer = join_renderer
        self.filter_renderer = filter_renderer
        self.group_renderer = group_renderer
        self.order_renderer = order_renderer
        self.limit_renderer = limit_renderer
        self.formatter = formatter
        
    @property
    def dialect_name(self) -> str:
        return self._dialect_name

    def render_relation(self, relation: DialectRelation) -> str:
        return self.join_renderer.render_relation(relation)
        
    def render_projection(self, projection: DialectProjection, param_builder: ParameterBuilder) -> str:
        return self.proj_renderer.render(projection, param_builder)
        
    def render_filter(self, filter_obj: DialectFilter, param_builder: ParameterBuilder) -> str:
        return self.filter_renderer.render(filter_obj, param_builder)
        
    def render_join(self, joins: List[DialectJoin], param_builder: ParameterBuilder) -> str:
        return self.join_renderer.render(joins, param_builder)
        
    def render_expression(self, expr: DialectExpression, param_builder: ParameterBuilder) -> str:
        return self.expr_renderer.render(expr, param_builder)
        
    def render_group_by(self, group_obj: DialectAggregate, param_builder: ParameterBuilder) -> str:
        return self.group_renderer.render(group_obj, param_builder)
        
    def render_order_by(self, order_obj: DialectSort, param_builder: ParameterBuilder) -> str:
        return self.order_renderer.render(order_obj, param_builder)
        
    def render_limit(self, limit_obj: DialectLimit, param_builder: ParameterBuilder) -> str:
        return self.limit_renderer.render(limit_obj, param_builder)

    def render(self, query: DialectQuery) -> SQLDocument:
        warnings = []
        param_style = determine_param_style(self._dialect_name)
        param_builder = ParameterBuilder(style=param_style)
        
        select_clause = self.render_projection(query.projections, param_builder)
        
        from_clause = ""
        if query.joins:
            from_clause = self.render_join(query.joins, param_builder)
        elif query.relations:
            from_clause = f"FROM {self.render_relation(query.relations[0])}"
            
        where_clause = self.render_filter(query.filters, param_builder) if query.filters else ""
        group_clause = self.render_group_by(query.groupings, param_builder) if query.groupings else ""
        order_clause = self.render_order_by(query.sorts, param_builder) if query.sorts else ""
        limit_clause = self.render_limit(query.limit, param_builder) if query.limit else ""
        
        raw_sql = f"SELECT {select_clause}\n{from_clause}\n{where_clause}\n{group_clause}\n{order_clause}\n{limit_clause}"
        
        formatted_sql = self.formatter.format(raw_sql)
        
        # Simplified hash logic for demonstration
        ast_hash = str(hash(raw_sql))
        
        return SQLDocument(
            query_id=query.query_id,
            sql=formatted_sql.strip(),
            parameters=param_builder.params,
            dialect=self._dialect_name,
            warnings=warnings,
            estimated_complexity=query.estimated_complexity,
            ast_hash=ast_hash,
            renderer_version="1.0.0",
            formatting_version="1.0.0"
        )
