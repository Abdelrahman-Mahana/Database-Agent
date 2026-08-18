"""Pre-action decision layer for the conversational database agent."""
from __future__ import annotations

import json
import re
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field

from app.semantic.models import ExecutionRoute, IntentType


class DecisionResult(BaseModel):
    """Minimal routing decision made before schema access or SQL generation."""

    route: ExecutionRoute = ExecutionRoute.CONVERSATION
    intent: IntentType = IntentType.OFF_TOPIC
    confidence: float = 0.0
    needs_database: bool = False
    needs_schema: bool = False
    needs_sql: bool = False
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    reason: str = ""
    source: str = "rules"


class DecisionLayer:
    """Choose the next action without forcing every message through SQL."""

    def __init__(self, fast_llm=None):
        self.fast_llm = fast_llm

    @staticmethod
    def _has_arabic(text: str) -> bool:
        return any("\u0600" <= ch <= "\u06FF" for ch in text)

    def _rules(self, question: str, conversation_history: str = "") -> Optional[DecisionResult]:
        q = re.sub(r"\s+", " ", question.strip().lower())
        if not q:
            return DecisionResult(route=ExecutionRoute.CONVERSATION, confidence=1.0, reason="empty")

        greeting_patterns = (
            r"^(hi|hello|hey|good morning|good evening|thanks|thank you)\b",
            r"^(مرحبا|اهلا|أهلا|السلام عليكم|شكرا|شكرًا)\b",
        )
        if any(re.search(p, q) for p in greeting_patterns):
            return DecisionResult(
                route=ExecutionRoute.CONVERSATION,
                intent=IntentType.GREETING,
                confidence=0.99,
                reason="greeting",
            )

        schema_terms = (
            "schema", "database schema", "show tables", "list tables", "describe table",
            "table structure", "columns", "relationships", "foreign key", "primary key",
            "هيكل قاعدة البيانات", "الجداول", "الجدول", "الأعمدة", "علاقة الجداول", "مفتاح أساسي", "مفتاح أجنبي",
        )
        if any(term in q for term in schema_terms):
            return DecisionResult(
                route=ExecutionRoute.SCHEMA,
                intent=IntentType.SCHEMA,
                confidence=0.97,
                needs_database=True,
                needs_schema=True,
                reason="schema/metadata request",
            )

        strong_data_terms = (
            "how many", "count", "number of", "sum", "total", "average", "avg", "mean",
            "max", "min", "highest", "lowest", "top", "bottom", "records", "rows", "data",
            "كم", "كام", "عدد", "إجمالي", "اجمالي", "مجموع", "متوسط", "احسب", "بيانات", "سجلات",
            "أعلى", "اقل", "أقل",
        )
        db_entity_terms = (
            "sales", "customers", "students", "orders", "طلاب", "الطلاب", "عملاء", "العملاء",
            "طلبات", "مبيعات", "الجداول", "البيانات",
        )
        retrieval_verbs = ("show me", "show", "list", "find", "get", "fetch", "retrieve", "give me", "هات", "وريني", "اعرض", "طلع", "هاتلي")
        has_strong_data = any(term in q for term in strong_data_terms)
        has_db_entity = any(term in q for term in db_entity_terms)
        has_retrieval_verb = any(q.startswith(term + " ") or (" " + term + " ") in q for term in retrieval_verbs)
        if has_strong_data or (has_db_entity and has_retrieval_verb):
            return DecisionResult(
                route=ExecutionRoute.DATA_QUERY,
                intent=IntentType.DATABASE,
                confidence=0.94,
                needs_database=True,
                needs_sql=True,
                reason="explicit data retrieval/analysis language",
            )

        # Contextual follow-ups such as "and what about Cairo?" should not
        # silently become a new SQL query. Let the model or user clarify.
        follow_up_patterns = (
            "what about", "and ", "how about", "what if", "and then", "ماذا عن", "طب و", "و", "طيب",
        )
        has_history = bool(conversation_history.strip())
        if has_history and any(q.startswith(prefix) for prefix in follow_up_patterns):
            return DecisionResult(
                route=ExecutionRoute.CONVERSATION,
                intent=IntentType.DATABASE,
                confidence=0.55,
                needs_clarification=True,
                reason="contextual follow-up is ambiguous",
            )

        return None

    async def decide(self, question: str, conversation_history: str = "") -> DecisionResult:
        """Resolve obvious routes cheaply, then use one small LLM call only when ambiguous."""
        quick = self._rules(question, conversation_history)
        if quick is not None and quick.confidence >= 0.90:
            return quick

        if not self.fast_llm:
            return quick or DecisionResult(
                route=ExecutionRoute.CONVERSATION,
                intent=IntentType.OFF_TOPIC,
                confidence=0.50,
                reason="general conversational request; no database signal",
            )

        history = conversation_history[-3500:] if conversation_history else "No previous conversation."
        language_rule = "Respond in natural Egyptian Arabic." if self._has_arabic(question) else "Respond in natural English."
        prompt = f"""
You are the decision layer of a conversational database assistant.
Your ONLY job is to choose the next action. Do not answer the user's request and do not write SQL.

Actions:
- conversation: normal conversation, explanation, general knowledge, or a response that does not need database data.
- clarify: the message is ambiguous and the assistant should ask one concise follow-up before taking any database action.
- schema: needs database metadata such as tables, columns, relationships, or structure, but not row-level data.
- data_query: needs actual database data; SQL may be generated later.

Important:
- Do NOT assume SQL is needed just because a database is connected.
- Use conversation history to resolve references like "that", "the first one", "what about it".
- If the request can be answered conversationally without database facts, choose conversation.
- If the user appears to ask for database data but the target is unclear, choose clarify.

Conversation history:
{history}

User message:
{question}

Return JSON only:
{{
  "action": "conversation|clarify|schema|data_query",
  "confidence": 0.0,
  "reason": "brief reason",
  "clarification_question": "only when action=clarify"
}}
{language_rule}
"""
        try:
            response = await self.fast_llm.ainvoke(prompt)
            content = getattr(response, "content", response)
            text = str(content).strip()
            if "```" in text:
                text = text.replace("```json", "").replace("```", "").strip()
            payload = json.loads(text)
            action = str(payload.get("action", "conversation")).lower()
            conf = max(0.0, min(1.0, float(payload.get("confidence", 0.5))))
            mapping = {
                "conversation": (ExecutionRoute.CONVERSATION, IntentType.OFF_TOPIC, False, False),
                "clarify": (ExecutionRoute.CONVERSATION, IntentType.DATABASE, True, False),
                "schema": (ExecutionRoute.SCHEMA, IntentType.SCHEMA, False, True),
                "data_query": (ExecutionRoute.DATA_QUERY, IntentType.DATABASE, False, False),
            }
            route, intent, clarification, needs_schema = mapping.get(action, mapping["conversation"])
            needs_db = action in {"schema", "data_query", "clarify"}
            needs_sql = action == "data_query"
            return DecisionResult(
                route=route,
                intent=intent,
                confidence=conf,
                needs_database=needs_db,
                needs_schema=needs_schema,
                needs_sql=needs_sql,
                needs_clarification=clarification,
                clarification_question=payload.get("clarification_question"),
                reason=str(payload.get("reason", "LLM decision")),
                source="llm",
            )
        except Exception as exc:
            logger.warning("Decision layer LLM fallback failed: %s", exc)
            return quick or DecisionResult(
                route=ExecutionRoute.CONVERSATION,
                intent=IntentType.OFF_TOPIC,
                confidence=0.40,
                reason="ambiguous/general request; safe conversational fallback",
                source="fallback",
            )
