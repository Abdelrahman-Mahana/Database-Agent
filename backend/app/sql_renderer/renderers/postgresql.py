from app.sql_renderer.renderer import DeterministicBaseRenderer

class PostgreSQLRenderer(DeterministicBaseRenderer):
    def __init__(self, ident_renderer, expr_renderer, proj_renderer, join_renderer, filter_renderer, group_renderer, order_renderer, limit_renderer, formatter):
        super().__init__(
            "postgresql", ident_renderer, expr_renderer, proj_renderer, join_renderer, filter_renderer, group_renderer, order_renderer, limit_renderer, formatter
        )
