"""SQL Repair Engine for self-healing error recovery and schema suggestion."""
import difflib
import logging
import re
from typing import Any, List, Optional, Tuple

from app.services.sql_service import SchemaService
from app.services.sql.prompt_builder import SQLPromptBuilder
from app.services.sql.validator import SQLValidator
from app.utils.helpers import extract_missing_identifier

logger = logging.getLogger(__name__)


class SQLRepairEngine:
    """Analyzes DB runtime failures and repairs SQL queries via LLM feedback."""

    def __init__(self, primary_llm):
        self.primary_llm = primary_llm
        self.prompt_builder = SQLPromptBuilder()
        self.sql_fix_chain = self.prompt_builder.fix_template | self.primary_llm
        self.schema_service = SchemaService()
        self.validator = SQLValidator()

    async def fix_sql(
        self,
        question: str,
        schema_text: str,
        failed_sql: str,
        error: str,
        dialect: str = "sqlite",
        query_understanding: Optional[Any] = None,
        conversation_history: str = "",
        db_identifier: str = "",
    ) -> str:
        """Ask the LLM to repair a failed SQL query using dialect-aware rules and semantic contract constraints."""
        payload = self.prompt_builder.build_fix_input(
            schema_text=schema_text,
            question=question,
            failed_sql=failed_sql,
            error=error,
            dialect=dialect,
            query_understanding=query_understanding,
            conversation_history=conversation_history,
            db_identifier=db_identifier,
        )
        response = await self.sql_fix_chain.ainvoke(payload)
        return self.validator.sanitize_and_extract(response.content)

    def analyze_db_error(self, error_msg: str) -> Tuple[str, List[str]]:
        """Analyze database error message and return (error_type, suggestions)."""
        error_lower = error_msg.lower()
        is_schema = any(
            x in error_lower for x in (
                "no such table", "no such column", "does not exist",
                "undefined_table", "undefined_column"
            )
        )
        error_type = "schema" if is_schema else "syntax"

        kind, missing_name = extract_missing_identifier(error_msg)
        if not missing_name:
            return error_type, []

        schema = self.schema_service.get_schema()
        if kind == "table":
            candidates = list(schema.keys())
        else:
            candidates = sorted({col["name"] for t_info in schema.values() for col in t_info["columns"]})

        suggestions = difflib.get_close_matches(missing_name, candidates, n=3, cutoff=0.5)
        return error_type, suggestions
