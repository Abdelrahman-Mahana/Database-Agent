"""Prompt Builder for SQL generation and repair."""
from typing import Any, Dict, Optional
from langchain_core.prompts import PromptTemplate
from app.llm.prompts import SQL_ZERO_SHOT_TEMPLATE, SQL_FIX_TEMPLATE
from app.semantic.models import QueryUnderstanding
from app.sql.dialect_rules import get_dialect_guidelines
from app.utils.text_processor import build_temporal_grounding_hint


class SQLPromptBuilder:
    """Formats structured prompts for initial SQL generation and self-healing repair."""

    def __init__(self):
        self.zero_shot_template = SQL_ZERO_SHOT_TEMPLATE
        self.fix_template = PromptTemplate(
            input_variables=["schema", "question", "sql", "error", "dialect_guidelines"],
            template=SQL_FIX_TEMPLATE
        )

    def build_generation_input(
        self,
        schema_text: str,
        question: str,
        conversation_history: str = "",
        query_understanding: Optional[QueryUnderstanding] = None,
        dialect: str = "sqlite",
    ) -> Dict[str, Any]:
        """Build input payload for the SQL generation LLM chain."""
        hint = build_temporal_grounding_hint(question, schema_text)
        history = conversation_history
        if hint:
            history = f"{hint}\n{history}".strip() if history else hint

        dialect_guidelines = get_dialect_guidelines(dialect)

        return {
            "schema": schema_text,
            "question": question,
            "conversation_history": history,
            "dialect_guidelines": dialect_guidelines,
        }

    def build_fix_input(
        self,
        schema_text: str,
        question: str,
        failed_sql: str,
        error: str,
        dialect: str = "sqlite",
    ) -> Dict[str, Any]:
        """Build input payload for the SQL fix/repair LLM chain."""
        dialect_guidelines = get_dialect_guidelines(dialect)
        return {
            "schema": schema_text,
            "question": question,
            "sql": failed_sql,
            "error": error,
            "dialect_guidelines": dialect_guidelines,
        }
