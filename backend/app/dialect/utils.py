def format_ast(ast) -> str:
    # A simple utility to convert DialectQuery tree to a string repr for debugging
    return f"DialectAST({ast.dialect_name})"
