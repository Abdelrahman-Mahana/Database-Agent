"""SQL query validator — enforces SELECT-only, read-only queries using sqlglot."""
import logging
import re
import sqlglot
from sqlglot import exp

logger = logging.getLogger(__name__)

# List of forbidden sqlglot expression types to enforce read-only SELECT safety
FORBIDDEN_EXPRESSION_TYPES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create,
    exp.Command, exp.Transaction, exp.Merge, exp.Schema, exp.Pragma,
)

FORBIDDEN_FUNCTIONS = {
    "pg_read_file", "pg_write_file", "pg_read_binary_file", "pg_ls_dir",
    "load_file", "into_outfile", "sys_eval", "sys_exec", "xp_cmdshell",
    "system", "eval", "sleep", "benchmark", "pg_sleep",
}

FORBIDDEN_SYSTEM_OBJECTS = {
    "pg_shadow", "pg_authid", "mysql.user", "information_schema.user_privileges",
    "master..syslogins", "master..sysprocesses",
}


def validate_sql(query: str) -> dict:
    """
    Validate that a SQL query is safe to execute using sqlglot AST parsing.
    Returns {"valid": bool, "reason": str, "query_type": str}
    """
    if not query or not query.strip():
        return {"valid": False, "reason": "Empty query", "query_type": "none"}

    # Check for raw multiple statements before sanitization
    raw_statements = [s.strip() for s in query.split(";") if s.strip()]
    if len(raw_statements) > 1:
        return {
            "valid": False,
            "reason": "Multiple SQL statements in a single request are forbidden.",
            "query_type": "unsafe",
        }

    cleaned = sanitize_query(query)
    if not cleaned:
        return {"valid": False, "reason": "No query found after sanitization", "query_type": "none"}

    try:
        target_dialect = get_target_dialect()
        # Parse all statements in the query
        statements = sqlglot.parse(cleaned, read=target_dialect)
        if not statements:
            return {"valid": False, "reason": "Could not parse SQL query", "query_type": "unknown"}

        if len(statements) > 1:
            return {
                "valid": False,
                "reason": "Multiple SQL statements in a single request are forbidden.",
                "query_type": "unsafe",
            }

        expression = statements[0]
        if expression is None:
            return {"valid": False, "reason": "Empty SQL statement", "query_type": "none"}

        # Traverse the AST to check for forbidden node types, functions, and system catalog access
        for node in expression.walk():
            if isinstance(node, FORBIDDEN_EXPRESSION_TYPES):
                return {
                    "valid": False,
                    "reason": f"Disallowed SQL operation detected: {node.__class__.__name__}. Only read-only SELECT queries are allowed.",
                    "query_type": "unsafe",
                }

            # Block dangerous functions
            if isinstance(node, (exp.Anonymous, exp.Func)):
                fname = getattr(node, "name", "") or ""
                if fname.lower() in FORBIDDEN_FUNCTIONS:
                    return {
                        "valid": False,
                        "reason": f"Forbidden administrative or file-access function detected: '{fname}'.",
                        "query_type": "unsafe",
                    }

            # Block sensitive system catalog access
            if isinstance(node, exp.Table):
                tname = node.name.lower()
                db_name = node.db.lower() if node.db else ""
                full_tname = f"{db_name}.{tname}" if db_name else tname
                if tname in FORBIDDEN_SYSTEM_OBJECTS or full_tname in FORBIDDEN_SYSTEM_OBJECTS:
                    return {
                        "valid": False,
                        "reason": f"Access to system catalog table '{full_tname}' is restricted.",
                        "query_type": "unsafe",
                    }

        # Ensure the statement is a Query, Select, Union, or CTE
        if not isinstance(expression, (exp.Query, exp.Select, exp.Union, exp.CTE, exp.Subquery)):
            return {
                "valid": False,
                "reason": f"Disallowed SQL statement structure: {expression.__class__.__name__}. Only SELECT queries are allowed.",
                "query_type": "unsafe",
            }

        return {"valid": True, "reason": "Query is safe", "query_type": "select"}

    except sqlglot.errors.ParseError as e:
        error_msg = re.sub(r'\x1b\[.*?m', '', str(e))
        return {
            "valid": False,
            "reason": f"SQL syntax error: {error_msg}",
            "query_type": "invalid"
        }
    except Exception as e:
        return {
            "valid": False,
            "reason": f"Validation error: {str(e)}",
            "query_type": "invalid"
        }


def transpile_sql_to_dialect(query: str, target_dialect: str) -> str:
    """
    Transpiles a query to the target dialect (e.g. 'sqlite' or 'postgres').
    If transpilation fails, returns the original query.
    """
    cleaned = sanitize_query(query)
    try:
        expression = sqlglot.parse_one(cleaned, read=target_dialect)
        
        # Enforce LIMIT (covers plain SELECT and UNION-style set queries;
        # both support .limit() in sqlglot). CTEs (WITH ... SELECT) are still
        # covered since their top-level node type is exp.Select.
        if isinstance(expression, (exp.Select, exp.Union)):
            if not expression.args.get("limit"):
                expression = expression.limit(500)
                
        return expression.sql(dialect=target_dialect, pretty=True)
    except Exception as e:
        logger.debug("Failed to transpile SQL to dialect '%s': %s", target_dialect, e)
        return cleaned


def get_target_dialect() -> str:
    """Determine target SQL dialect dynamically from active database engine."""
    from app.services.database import db
    try:
        name = db.get_engine().dialect.name.lower()
        if name in ("postgres", "postgresql"):
            return "postgres"
        elif name in ("mysql", "mariadb"):
            return "mysql"
        elif name == "oracle":
            return "oracle"
        elif name in ("mssql", "microsoft"):
            return "tsql"
        return "sqlite"
    except Exception:
        return "sqlite"


from app.utils.text_processor import sanitize_query

