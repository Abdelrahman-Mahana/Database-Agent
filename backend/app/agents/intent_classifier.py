"""Module for classifying user intents and handling off-topic interactions."""
import json
import re
from typing import Any
from loguru import logger
from langchain_core.prompts import PromptTemplate

from app.llm.prompts import INTENT_CLASSIFICATION_TEMPLATE, OFF_TOPIC_RESPONSE_TEMPLATE
from app.services.sql_service import SchemaService
from app.utils.text_processor import extract_json_text
from app.config.settings import settings


class IntentClassifier:
    """Classifies user intent (database vs off-topic vs schema) and handles off-topic replies."""

    def __init__(self, fast_llm=None):
        self.schema_service = SchemaService()
        self.fast_llm = fast_llm

        if self.fast_llm is not None:
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
        else:
            self.intent_classification_chain = None
            self.off_topic_chain = None

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
            "highest", "lowest", "best", "worst", "all", "customers", "invoices", "orders", "users",
            "كم", "كم عدد", "اعلى", "أعلى", "اجمالي", "إجمالي", "عدد", "ماهو", "ما هو", "ماهي", "ما هي",
            "اريد", "أريد", "عرض", "مجموع", "اكبر", "أكبر", "اقل", "أقل", "افضل", "أفضل", "اسوأ", "أسوأ",
            "هات", "طلع", "احسب", "من هم", "ماهم", "جميع", "كل", "بيانات"
        }
        words = set(re.findall(r'[\w\u0600-\u06FF]+', q_lower))
        
        schema_overlap = False
        try:
            db_ctx = self.schema_service.get_database_context()
            if db_ctx and db_ctx.keyword_to_tables:
                if words.intersection(db_ctx.keyword_to_tables.keys()):
                    schema_overlap = True
            elif db_ctx and db_ctx.table_names_set:
                if words.intersection({t.lower() for t in db_ctx.table_names_set}):
                    schema_overlap = True
        except Exception:
            pass

        if words.intersection(db_indicators) or schema_overlap:
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
        """Generate a polite off-topic refusal deterministically without extra LLM cost."""
        is_arabic = any("\u0600" <= c <= "\u06FF" for c in question)
        if is_arabic:
            return (
                "أنا مساعد متخصص في تحليل قواعد البيانات. يمكنني مساعدتك في الاستعلام عن البيانات، "
                "تحليل الاتجاهات، إنشاء التقارير، وتوليد استعلامات SQL. يرجى طرح سؤال يتعلق بقاعدة البيانات المتصلة."
            )
        return (
            "I specialize in database analysis and can help you query data, "
            "analyze trends, generate reports, explain the schema, or write SQL queries. "
            "Please ask a question related to the connected database."
        )

    def get_table_summary(self) -> str:
        """Return a compact summary of tables and key columns for LLM context.

        For large schemas (> settings.llm_prompt_max_tables), we show only
        table names (no columns) to stay within LLM payload limits. Intent
        classification only needs table names to decide database vs off_topic.
        """
        try:
            schema = self.schema_service.get_schema()
            max_tables = settings.llm_prompt_max_tables

            if len(schema) <= max_tables:
                # Small schema: original behavior with columns
                summary_parts = []
                for table_name, info in schema.items():
                    cols = [col["name"] for col in info.get("columns", [])[:5]]
                    cols_str = ", ".join(cols)
                    if len(info.get("columns", [])) > 5:
                        cols_str += ", ..."
                    summary_parts.append(f"- {table_name} ({cols_str})")
                return "\n".join(summary_parts)

            # Large schema: table names only (compact), capped
            table_names = sorted(schema.keys())[:max_tables]
            header = f"[{len(table_names)} of {len(schema)} tables shown]"
            return header + "\n" + "\n".join(f"- {t}" for t in table_names)
        except Exception as e:
            logger.warning("Failed to get schema table summary: %s", e)
            return "No tables available"
