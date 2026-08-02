"""Module for classifying user intents and handling off-topic interactions."""
import json
import re
from typing import Any
from loguru import logger
from langchain_core.prompts import PromptTemplate

from app.llm.prompts import INTENT_CLASSIFICATION_TEMPLATE, OFF_TOPIC_RESPONSE_TEMPLATE
from app.services.sql_service import SchemaService
from app.utils.text_processor import extract_json_text


class IntentClassifier:
    """Classifies user intent (database vs off-topic vs schema) and handles off-topic replies."""

    def __init__(self, fast_llm):
        self.schema_service = SchemaService()
        self.fast_llm = fast_llm

        # Create chains using LCEL (prompt | llm)
        self.intent_classification_chain = (
            PromptTemplate(
                input_variables=["table_names", "question", "conversation_history"],
                template=INTENT_CLASSIFICATION_TEMPLATE
            )
            | self.fast_llm
        )

        self.off_topic_chain = (
            PromptTemplate(
                input_variables=["table_names", "question"],
                template=OFF_TOPIC_RESPONSE_TEMPLATE
            )
            | self.fast_llm
        )

    def _quick_classify_intent(self, question: str) -> str | None:
        """Fast 0-token rule-based intent classifier to save LLM tokens and latency."""
        q_lower = question.strip().lower()
        
        # 1. Greetings & general conversational
        greetings = {"hi", "hello", "hey", "good morning", "good evening", "who are you", "what can you do", "help", "thanks", "thank you", "tell me a joke", "مرحبا", "اهلا", "السلام عليكم", "من انت", "شكرا"}
        if q_lower in greetings or any(q_lower.startswith(g + " ") for g in ("hi", "hello", "hey", "مرحبا", "اهلا")):
            if not any(kw in q_lower for kw in ("table", "data", "select", "count", "show", "artist", "customer", "sales", "invoice")):
                return "off_topic"
                
        # 2. Explicit schema exploration queries
        schema_kw = {"show tables", "list tables", "describe table", "schema", "database schema", "show schema", "ما هي الجداول", "هيكل البيانات"}
        if any(kw in q_lower for kw in schema_kw):
            return "schema"
            
        # 3. Analytical DB query indicators (broad coverage)
        db_indicators = {
            "select", "count", "sum", "avg", "average", "top", "most", "total", "sales", "revenue",
            "list", "show", "get", "find", "which", "how many", "what is", "what are", "breakdown",
            "customer", "invoice", "artist", "album", "track", "genre", "employee", "playlist",
            "كم", "اعلى", "اجمالي", "عدد", "ماهو", "ماهي", "اريد", "عرض", "مجموع"
        }
        words = set(re.findall(r'\w+', q_lower))
        
        # We only force 'database' if we find an indicator AND we see some schema keyword 
        # (or at least let the LLM decide if it's borderline)
        # However, for 0-token heuristic to be safe, if we just see '?' we should NOT automatically route to DB.
        schema_overlap = False
        try:
            schema = self.schema_service.get_schema()
            schema_terms = set()
            for t_name, info in schema.items():
                schema_terms.update(re.findall(r'\w+', t_name.lower()))
                for c in info.get("columns", []):
                    schema_terms.update(re.findall(r'\w+', c["name"].lower()))
            if words.intersection(schema_terms):
                schema_overlap = True
        except Exception:
            pass

        if words.intersection(db_indicators) and schema_overlap:
            return "database"
            
        # If we have a question mark but no clear schema match, let the LLM decide.
        return None

    async def classify_intent(self, question: str, conversation_history: str = "") -> dict[str, Any]:
        """Classify user intent as database, schema, or off_topic using fast heuristic rules first, falling back to LLM."""
        quick_intent = self._quick_classify_intent(question)
        if quick_intent:
            logger.info(f"Intent classified via 0-token heuristic: {quick_intent}")
            return {"intent": quick_intent, "reasoning": "Resolved via fast rule-based classifier."}

        try:
            table_summary = self.get_table_summary()
            response = await self.intent_classification_chain.ainvoke({
                "table_names": table_summary,
                "question": question,
                "conversation_history": conversation_history
            })
            text = extract_json_text(response.content)
            data = json.loads(text)
            intent = data.get("intent", "database").lower()
            if intent not in ("database", "schema", "off_topic"):
                intent = "database"
            return {"intent": intent, "reasoning": data.get("reasoning", "")}
        except Exception as e:
            logger.warning("Intent classification failed, defaulting to 'database'. Error: %s", e)
            return {"intent": "database", "reasoning": f"Fallback due to error: {e}"}

    async def generate_off_topic_response(self, question: str) -> str:
        """Generate a polite off-topic refusal with suggestions."""
        try:
            table_summary = self.get_table_summary()
            response = await self.off_topic_chain.ainvoke({
                "table_names": table_summary,
                "question": question
            })
            return response.content.strip()
        except Exception as e:
            logger.warning("Failed to generate off-topic response, using generic fallback. Error: %s", e)
            return (
                "I specialize in database analysis and can help you query data, "
                "analyze trends, generate reports, explain the schema, or write SQL queries. "
                "Please ask a question related to the connected database."
            )

    def get_table_summary(self) -> str:
        """Return a compact summary of tables and key columns for LLM context."""
        try:
            schema = self.schema_service.get_schema()
            summary_parts = []
            for table_name, info in schema.items():
                cols = [col["name"] for col in info.get("columns", [])[:5]]
                cols_str = ", ".join(cols)
                if len(info.get("columns", [])) > 5:
                    cols_str += ", ..."
                summary_parts.append(f"- {table_name} ({cols_str})")
            return "\n".join(summary_parts)
        except Exception as e:
            logger.warning("Failed to get schema table summary: %s", e)
            return "No tables available"
