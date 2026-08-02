from app.sql_renderer.renderer import DeterministicBaseRenderer

class RedshiftRenderer(DeterministicBaseRenderer):
    def __init__(self, ident_renderer, expr_renderer, proj_renderer, join_renderer, filter_renderer, group_renderer, order_renderer, limit_renderer, formatter):
        super().__init__(
            "redshift", ident_renderer, expr_renderer, proj_renderer, join_renderer, filter_renderer, group_renderer, order_renderer, limit_renderer, formatter
        )
