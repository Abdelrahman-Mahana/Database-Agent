"""Prompt Builder for SQL generation and repair."""
from typing import Any, Dict, Optional
from langchain_core.prompts import PromptTemplate
from app.llm.prompts import SQL_ZERO_SHOT_TEMPLATE, SQL_FIX_TEMPLATE
from app.semantic.models import QueryUnderstanding
from app.utils.text_processor import build_temporal_grounding_hint


class SQLPromptBuilder:
    """Formats structured prompts for initial SQL generation and self-healing repair."""

    def __init__(self):
        self.zero_shot_template = SQL_ZERO_SHOT_TEMPLATE
        self.fix_template = PromptTemplate(
            input_variables=["schema", "question", "sql", "error"],
            template=SQL_FIX_TEMPLATE
        )

    def build_generation_input(
        self,
        schema_text: str,
        question: str,
        conversation_history: str = "",
        query_understanding: Optional[QueryUnderstanding] = None,
    ) -> Dict[str, Any]:
        """Build input payload for the SQL generation LLM chain."""
        # Deterministically resolve bare month references (e.g. "January
        # sales" with no year) against the actual date range in the schema,
        # instead of relying on the LLM to notice/follow a comment buried in
        # a long schema block - front-and-center instructions are followed
        # far more reliably than embedded schema comments, especially by
        # smaller/weaker models.
        hint = build_temporal_grounding_hint(question, schema_text)
        history = conversation_history
        if hint:
            history = f"{hint}\n{history}".strip() if history else hint
        return {
            "schema": schema_text,
            "question": question,
            "conversation_history": history,
        }


    def build_fix_input(
        self,
        schema_text: str,
        question: str,
        failed_sql: str,
        error: str,
    ) -> Dict[str, Any]:
        """Build input payload for the SQL fix/repair LLM chain."""
        return {
            "schema": schema_text,
            "question": question,
            "sql": failed_sql,
            "error": error,
        }
