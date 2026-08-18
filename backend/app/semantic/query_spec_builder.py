"""Unified QuerySpec Builder — Consolidates Intent, Semantic Understanding, and Planning."""
import re
from typing import Any, Dict, Optional, List
from loguru import logger

from app.semantic.models import QuerySpec, IntentType, ExecutionRoute, FilterCondition, SortCondition, OutputFormat
from app.semantic.synonyms import resolve_synonyms
from app.utils.text_processor import classify_analysis_type, AnalysisType, COMPLEX_ANALYSIS_TYPES
from app.schema_catalog.models import SchemaCatalog
from app.config.settings import settings


class QuerySpecBuilder:
    """
    Unified QuerySpec Engine.
    Combines Intent Classification, Semantic Parsing, Business Synonym Resolution,
    and Planning Detection into a single, high-performance, single-pass pipeline.
    """

    def __init__(self, fast_llm=None):
        self.fast_llm = fast_llm

    def _quick_route(
        self,
        q_lower: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> tuple[ExecutionRoute, IntentType, float, Optional[str]]:
        """
        Decide the user's desired interaction mode before any schema grounding or SQL.

        Priority:
        1) greetings / normal conversation
        2) schema/metadata explanation
        3) real database-data requests
        4) conversation fallback for ambiguous/general questions
        """
        normalized = re.sub(r"\s+", " ", q_lower).strip()
        words = set(re.findall(r'[\w\u0600-\u06FF]+', normalized))

        # Greetings: keep backward-compatible OFF_TOPIC intent but route as conversation.
        greeting_phrases = {
            "hi", "hello", "hey", "good morning", "good evening", "thanks",
            "thank you", "who are you", "what can you do",
            "مرحبا", "أهلا", "اهلا", "السلام عليكم", "شكرا", "من انت", "من أنت",
            "ممكن تساعدني",
        }
        clean_no_punct = re.sub(r"[^\w\s\u0600-\u06FF]", " ", q_lower).strip()
        clean_normalized = re.sub(r"\s+", " ", clean_no_punct)

        if any(p == clean_normalized for p in greeting_phrases) or any(clean_normalized.startswith(p + " ") for p in ("hi", "hello", "hey", "مرحبا", "اهلا", "أهلا", "thanks", "thank you")):
            is_ar = any("\u0600" <= c <= "\u06FF" for c in normalized)
            reply = (
                "أهلاً بيك! أنا مساعد قواعد بيانات تفاعلي. اسألني عن البيانات أو الجداول أو أي شيء عام، وأنا أحدد لك الطريقة المناسبة للإجابة."
                if is_ar else
                "Hello! I’m a conversational database assistant. Ask me about your data, schema, or anything general, and I’ll choose the right way to help."
            )
            return ExecutionRoute.CONVERSATION, IntentType.OFF_TOPIC, 0.99, reply

        schema_terms = {
            "schema", "columns", "fields", "primary key", "foreign key",
            "relationship", "relationships", "database structure", "database schema",
            "describe table", "show tables", "list tables", "table details",
            "database overview", "describe database",
            "اشرح الجدول", "اشرح الجداول", "اوصف الجداول", "وصف الجداول",
            "اشرح قاعدة البيانات", "اشرح قواعد البيانات", "وصف قاعدة البيانات",
            "وصف قواعد البيانات", "هيكل قاعدة البيانات", "هيكل البيانات",
            "أعمدة", "اعمدة", "علاقة", "علاقات", "المفتاح الأساسي", "المفتاح الأجنبي",
            "مفتاح أساسي", "مفتاح أجنبي",
        }
        schema_cues = {
            "schema", "table", "tables", "column", "columns", "field", "fields",
            "database structure", "database schema", "structure", "relationships",
            "جدول", "جداول", "الجدول", "الجداول", "عمود", "أعمدة", "اعمدة",
            "هيكل", "علاقة", "علاقات", "مفتاح",
        }
        explain_cues = {
            "explain", "describe", "overview", "structure", "what tables", "which tables",
            "اشرح", "شرح", "اوصف", "وصف", "موجودة", "الموجودة", "عندك", "دي", "هذه",
        }
        connected_db_cues = {
            "this database", "the database", "these tables", "current database", "available tables",
            "قاعدة البيانات دي", "قواعد البيانات دي", "قاعدة البيانات الموجودة", "قواعد البيانات الموجودة",
            "الجداول دي", "الجداول الموجودة", "الجداول عندك", "البيانات الموجودة",
            "المتصلة", "الحالية",
        }

        has_explicit_schema = any(term in normalized for term in schema_terms)
        has_schema_pair = bool(words.intersection(schema_cues)) and bool(words.intersection(explain_cues))
        has_connected_schema = any(term in normalized for term in connected_db_cues)
        has_table_entity = False
        if schema:
            for table_name in schema.keys():
                t = str(table_name).lower()
                if t and (re.search(rf"\b{re.escape(t)}\b", normalized) or t in normalized):
                    has_table_entity = True
                    break

        relationship_language = (
            "difference between" in normalized
            or "compare table" in normalized
            or "relationship between" in normalized
            or "الفرق بين" in normalized
            or "قارن بين" in normalized
            or "العلاقة بين" in normalized
        )
        if has_explicit_schema or has_schema_pair or has_connected_schema or ((has_table_entity or "جدول" in normalized or "جداول" in normalized or "table" in normalized) and relationship_language):
            return ExecutionRoute.SCHEMA, IntentType.SCHEMA, 0.97, None

        data_cues = {
            "count", "how many", "number of", "sum", "total", "average", "avg",
            "max", "min", "highest", "lowest", "top", "bottom", "most", "least",
            "show", "list", "find", "get", "fetch", "search", "give me", "retrieve",
            "data", "records", "rows", "customers", "students", "orders", "sales",
            "كم", "كام", "كم عدد", "عدد", "اجمالي", "إجمالي", "مجموع", "متوسط",
            "احسب", "هات", "هاتلي", "طلع", "وريني", "اعرض", "بيانات", "سجلات",
            "طلاب", "الطلاب", "عملاء", "العملاء", "طلبات", "مبيعات", "أعلى", "اعلى",
            "أقل", "اقل", "أفضل", "افضل",
        }
        analysis_signal = classify_analysis_type(normalized) != AnalysisType.UNKNOWN
        has_data_cue = any(cue in normalized for cue in data_cues)
        if has_table_entity and (has_data_cue or analysis_signal):
            return ExecutionRoute.DATA_QUERY, IntentType.DATABASE, 0.96, None
        if analysis_signal and has_data_cue:
            return ExecutionRoute.DATA_QUERY, IntentType.DATABASE, 0.93, None

        # Explicitly general / ambiguous requests stay conversational rather than
        # falling through to SQL. This is the key safety/UX default.
        is_ar = any("\u0600" <= c <= "\u06FF" for c in normalized)
        return ExecutionRoute.CONVERSATION, IntentType.OFF_TOPIC, 0.60, None

    def _quick_intent(self, q_lower: str, schema: Optional[Dict[str, Any]] = None) -> Optional[tuple[IntentType, str]]:
        """Fast 0-token rule-based intent checker."""
        words = set(re.findall(r'[\w\u0600-\u06FF]+', q_lower))

        # 1. Greetings & general conversational
        greetings = {
            "hi", "hello", "hey", "good morning", "good evening", "who are you",
            "what can you do", "help", "thanks", "thank you", "tell me a joke",
            "مرحبا", "اهلا", "أهلا", "السلام عليكم", "من انت", "من أنت", "شكرا", "صباح الخير", "مساء الخير"
        }
        greeting_words = {"hi", "hello", "hey", "مرحبا", "اهلا", "أهلا", "شكرا", "thanks"}
        if words.intersection(greetings) or words.intersection(greeting_words) or any(q_lower.startswith(g) for g in ("hi", "hello", "hey", "مرحبا", "اهلا", "أهلا")):
            if not words.intersection({"table", "tables", "data", "select", "count", "show", "artist", "customer", "sales", "invoice", "جدول", "جداول", "بيانات", "مبيعات", "عملاء"}):
                is_ar = any("\u0600" <= c <= "\u06FF" for c in q_lower)
                greeting_reply = (
                    "مرحباً بك! أنا مساعد قواعد البيانات الذكي، يمكنني مساعدتك في استخراج البيانات، كتابة استعلامات SQL، وتحليل الأرقام والمؤشرات. كيف يمكنني خدمتك اليوم؟"
                    if is_ar else
                    "Hello! I am your AI Database Assistant. I can help you query, analyze, and visualize your database. How can I help you today?"
                )
                return IntentType.OFF_TOPIC, greeting_reply

        # 2. Explicit schema exploration queries
        schema_kw = {"show tables", "list tables", "describe table", "schema", "database schema", "show schema", "ما هي الجداول", "هيكل البيانات", "عرض الجداول"}
        if any(kw in q_lower for kw in schema_kw):
            return IntentType.SCHEMA, ""

        return None

    def build_spec(
        self,
        question: str,
        schema: Optional[Dict[str, Any]] = None,
        conversation_history: str = "",
        catalog: Optional[SchemaCatalog] = None,
        route_override: Optional[ExecutionRoute] = None,
    ) -> QuerySpec:
        """
        Build the unified QuerySpec in a single fast pass.
        """
        if not question or not question.strip():
            return QuerySpec(raw_question=question or "", intent=IntentType.OFF_TOPIC)

        q = question.strip()
        q_lower = q.lower()

        # Step 1: Decide execution route BEFORE semantic parsing/SQL.
        route, intent_type, route_confidence, route_reply = self._quick_route(q_lower, schema)
        if route_override is not None:
            route = route_override
            intent_type = {
                ExecutionRoute.CONVERSATION: IntentType.OFF_TOPIC,
                ExecutionRoute.SCHEMA: IntentType.SCHEMA,
                ExecutionRoute.DATA_QUERY: IntentType.DATABASE,
                ExecutionRoute.CLARIFY: IntentType.DATABASE,
            }.get(route_override, intent_type)
        if route in (ExecutionRoute.CONVERSATION, ExecutionRoute.SCHEMA):
            return QuerySpec(
                raw_question=q,
                intent=intent_type,
                route=route,
                route_confidence=route_confidence,
                off_topic_response=route_reply,
                source="deterministic_router",
                analysis_type=AnalysisType.UNKNOWN,
            )

        # Step 2: Extract Semantic Components only for real data questions.
        analysis_type = classify_analysis_type(q)
        entities: List[str] = []
        metrics: List[str] = []
        dimensions: List[str] = []

        if schema:
            words = set(re.findall(r'[\w\u0600-\u06FF]+', q_lower))
            if len(schema) > 30:
                candidate_tables = [
                    t for t in schema.keys()
                    if t.lower() in words or t.lower().rstrip("s") in words or t.lower() in q_lower
                ]
                for t in candidate_tables:
                    entities.append(t)
                    table_info = schema.get(t, {})
                    for col in table_info.get("columns", []):
                        col_name = col["name"]
                        c_lower = col_name.lower()
                        if (c_lower in words or c_lower in q_lower) and c_lower not in ("id", "created_at"):
                            col_type = col.get("type", "").upper()
                            is_numeric = any(num_t in col_type for num_t in ("INT", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL", "REAL"))
                            full_ref = f"{t}.{col_name}"
                            if is_numeric:
                                if full_ref not in metrics:
                                    metrics.append(full_ref)
                            else:
                                if full_ref not in dimensions:
                                    dimensions.append(full_ref)
            else:
                for table_name, table_info in schema.items():
                    t_lower = table_name.lower()
                    t_singular = t_lower.rstrip("s")
                    if t_lower in q_lower or (len(t_singular) > 3 and t_singular in q_lower):
                        entities.append(table_name)

                    for col in table_info.get("columns", []):
                        col_name = col["name"]
                        c_lower = col_name.lower()
                        if c_lower in q_lower and c_lower not in ("id", "created_at"):
                            col_type = col.get("type", "").upper()
                            is_numeric = any(num_t in col_type for num_t in ("INT", "FLOAT", "DOUBLE", "NUMERIC", "DECIMAL", "REAL"))
                            full_ref = f"{table_name}.{col_name}"
                            if is_numeric:
                                if full_ref not in metrics:
                                    metrics.append(full_ref)
                            else:
                                if full_ref not in dimensions:
                                    dimensions.append(full_ref)

        # Step 3: Aggregations, Limit, Sorting, Time Expressions
        aggregations: List[str] = []
        if re.search(r"\b(how many|count|number of|كم|كم عدد|عدد|احسب)\b", q_lower):
            aggregations.append("COUNT")
        if re.search(r"\b(total|sum|مجموع|اجمالي|إجمالي)\b", q_lower):
            aggregations.append("SUM")
        if re.search(r"\b(average|avg|mean|متوسط|معدل)\b", q_lower):
            aggregations.append("AVG")
        if re.search(r"\b(highest|maximum|max|most|اكبر|أكبر|اعلى|أعلى|اكثر|أكثر|اكتر|حد أقصى)\b", q_lower):
            aggregations.append("MAX")
        if re.search(r"\b(lowest|minimum|min|least|اصغر|أصغر|اقل|أقل|حد ادنى)\b", q_lower):
            aggregations.append("MIN")

        limit: Optional[int] = None
        limit_match = re.search(r"\b(?:top|first|limit|best|worst|اول|أول|افضل|أفضل|اسوأ|أسوأ|اعلى|أعلى)\s+(\d+)\b", q_lower)
        if not limit_match:
            limit_match = re.search(r"\b(\d+)\s+(?:top|best|worst|artists|tracks|customers|albums|افضل|أفضل|اسوأ|أسوأ|الاوائل|الأوائل)\b", q_lower)
        if limit_match:
            try:
                limit = int(limit_match.group(1))
            except ValueError:
                pass

        sorting: List[SortCondition] = []
        if re.search(r"\b(top|highest|best|most|اعلى|أعلى|افضل|أفضل|اكثر|أكثر|اكتر)\b", q_lower):
            sorting.append(SortCondition(direction="DESC"))
        elif re.search(r"\b(bottom|lowest|worst|least|اقل|أقل|اسوأ|أسوأ)\b", q_lower):
            sorting.append(SortCondition(direction="ASC"))

        time_expressions: List[str] = []
        year_matches = re.findall(r"\b(19\d\d|20\d\d)\b", q)
        time_expressions.extend(year_matches)

        filters: List[FilterCondition] = []
        for year in year_matches:
            filters.append(FilterCondition(operator="=", value=year, raw_expression=f"year = {year}"))

        expected_output = OutputFormat.TABLE
        if analysis_type == AnalysisType.COUNT or (aggregations == ["COUNT"] and not dimensions):
            expected_output = OutputFormat.SCALAR
        elif limit is not None or analysis_type == AnalysisType.RANKING:
            expected_output = OutputFormat.RANKING

        # Step 4: Multi-step planning detection
        requires_multi_step = analysis_type in COMPLEX_ANALYSIS_TYPES

        spec = QuerySpec(
            raw_question=q,
            intent=IntentType.DATABASE,
            route=ExecutionRoute.DATA_QUERY,
            route_confidence=route_confidence,
            analysis_type=analysis_type,
            entities=entities,
            metrics=metrics,
            dimensions=dimensions,
            filters=filters,
            time_expressions=time_expressions,
            aggregations=aggregations,
            sorting=sorting,
            limit=limit,
            expected_output=expected_output,
            requires_multi_step=requires_multi_step,
            confidence=1.0,
            source="unified_query_spec_builder",
        )

        # Step 5: Resolve business synonyms against catalog if available
        if catalog is not None:
            try:
                spec = resolve_synonyms(q, catalog, spec)
            except Exception as e:
                logger.debug("Synonym resolution skipped in QuerySpecBuilder: %s", e)

        return spec
