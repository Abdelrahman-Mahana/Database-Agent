"""SQL Validator for safety rules, dialect transpilation, and dry-run execution checks."""
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.services.sql_service import SQLExecutor
from app.utils.validator import validate_sql, sanitize_query, transpile_sql_to_dialect, get_target_dialect
from app.utils.text_processor import extract_sql, normalize_sql


class SQLValidator:
    """Performs safety checks, syntax validation, dialect transpilation, and execution checks."""

    def __init__(self):
        self.sql_executor = SQLExecutor()

    def sanitize_and_extract(self, raw_response: str) -> str:
        """Extract SQL from markdown fences and sanitize it."""
        return sanitize_query(extract_sql(raw_response))

    def transpile(self, sql: str, target_dialect: str | None = None) -> str:
        """Transpile SQL query to target database dialect."""
        dialect = target_dialect or get_target_dialect()
        return transpile_sql_to_dialect(sql, dialect)

    def validate_safety(self, sql: str) -> Dict[str, Any]:
        """Run safety validation rules on SQL statement."""
        return validate_sql(sql)

    def validate_execution(self, sql: str, db: Session) -> Tuple[bool, Optional[str]]:
        """Perform dry-run execution check on SQL statement against database session."""
        try:
            self.sql_executor.execute(sql, db)
            return True, None
        except Exception as e:
            return False, str(e)
