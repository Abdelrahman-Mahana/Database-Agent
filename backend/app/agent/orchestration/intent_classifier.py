"""Adapter module wrapping QuerySpecBuilder for backward-compatibility."""
from typing import Any, Optional
from app.agent.semantic.query_spec_builder import QuerySpecBuilder
from app.agent.semantic.models import IntentType
from app.services.sql_service import SchemaService


class IntentClassifier:
    """Adapter wrapping QuerySpecBuilder for backward-compatible intent classification."""

    def __init__(self, fast_llm=None):
        self.spec_builder = QuerySpecBuilder(fast_llm=fast_llm)
        self.schema_service = SchemaService()

    async def classify_intent(self, question: str, conversation_history: str = "") -> dict[str, Any]:
        """Classify user intent using canonical QuerySpecBuilder."""
        db_ctx = None
        try:
            db_ctx = self.schema_service.get_database_context()
        except Exception:
            pass

        spec = self.spec_builder.build_spec(
            question=question,
            db_ctx=db_ctx,
            conversation_history=conversation_history,
        )

        intent_map = {
            IntentType.DATABASE: "database",
            IntentType.SCHEMA: "schema",
            IntentType.OFF_TOPIC: "off_topic",
        }
        return {
            "intent": intent_map.get(spec.intent, "database"),
            "reasoning": f"Canonical QuerySpec route: {spec.route.value}",
        }

    async def generate_off_topic_response(self, question: str) -> str:
        """Return deterministic database-scoped off-topic response."""
        is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
        if is_arabic:
            return (
                "أنا مساعد متخصص في استعلام وتحليل قواعد البيانات. يمكنني مساعدتك في استعراض الجداول، "
                "حساب المؤشرات، وكتابة استعلامات SQL. يرجى توجيه سؤالك حول قاعدة البيانات أو البيانات المتصلة."
            )
        return (
            "I specialize in database analysis and can help you query data, "
            "analyze trends, generate reports, explain the schema, or write SQL queries. "
            "Please ask a question related to the connected database."
        )
