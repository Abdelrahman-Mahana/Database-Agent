def format_expression(expr) -> str:
    # A simple utility to convert LogicalExpression tree to string for debugging, not for SQL gen
    return str(expr.expr_type.value)
