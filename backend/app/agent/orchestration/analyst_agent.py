"""Analyst Agent — canonical AI Database Analyst orchestrating via unified LangGraph pipeline."""
from typing import Any, Optional
from sqlalchemy.orm import Session
from loguru import logger

from app.agent.llm.model import get_llm_client, get_langchain_llm
from app.services.sql_service import SchemaService
from app.services.report_service import ReportService
from app.services.memory import memory_manager
from app.agent.orchestration.schema_explorer import SchemaExplorer
from app.agent.orchestration.sql_generator import SQLGenerator
from app.agent.orchestration.planner import Planner
from app.agent.schema_grounding.grounding_engine import SchemaGroundingEngine
from app.services.analytics import AnalyticsEngine, InsightEngine
from app.agent.semantic.query_spec_builder import QuerySpecBuilder
from app.agent.semantic.models import ExecutionRoute
from app.models.schema_catalog.catalog_builder import CatalogBuilder
from app.core.config.settings import settings

# --- Tunables -----------------------------------------------------------
LLM_TEMPERATURE = 0.1          # low temperature: we want deterministic, correct SQL
MAX_FIX_ATTEMPTS = getattr(settings, "max_fix_attempts", 1)  # bounded auto-repair attempts
MAX_ROWS_FOR_LLM = 200         # cap rows sent to the report/chart LLM calls (cost + context safety)


class AnalystAgent:
    """
    Canonical End-to-End Database Analyst Agent implementing the unified orchestration contract
    via LangGraph as the single authoritative orchestrator.
    """

    def __init__(self):
        self.llm = get_llm_client()
        self.schema_service = SchemaService()
        self.report_service = ReportService()
        self.schema_grounding_engine = SchemaGroundingEngine(self.schema_service)
        self.catalog_builder = CatalogBuilder(self.schema_service)

        # LangChain LLMs
        self.primary_llm = get_langchain_llm(tier="primary", temperature=LLM_TEMPERATURE)
        self.self_consistency_llm = get_langchain_llm(tier="primary", temperature=0.7)
        self.fast_llm = get_langchain_llm(tier="fast", temperature=0.1)

        # Canonical components
        from app.services.analysis.planner import AnalysisPlanner
        self.schema_explorer = SchemaExplorer(llm=self.fast_llm)
        self.sql_generator = SQLGenerator(self.primary_llm, self.self_consistency_llm, fast_llm=self.fast_llm)
        self.query_spec_builder = QuerySpecBuilder(self.fast_llm)
        self.analysis_planner = AnalysisPlanner(self.fast_llm)
        self.planner = Planner(self.primary_llm, self.fast_llm)
        self.analytics_engine = AnalyticsEngine()
        self.insight_engine = InsightEngine()
        self._graph = None

    def get_or_build_graph(self):
        """Lazily build+cache the LangGraph orchestrator for this agent instance."""
        if self._graph is None:
            from app.agent.orchestration.graph_orchestrator import build_analyst_graph
            self._graph = build_analyst_graph(self)
        return self._graph

    async def _run_graph_pipeline(
        self,
        question: str,
        db: Session,
        memory,
        conversation_history: str,
        req_start: float,
    ) -> dict[str, Any]:
        """Canonical LangGraph orchestration path."""
        import time
        from app.agent.orchestration.graph_orchestrator import run_graph_ask

        try:
            return await run_graph_ask(self, question, db, memory, conversation_history)
        except Exception as e:
            logger.exception("LangGraph orchestration failed for question=%r: %s", question, e)
            is_ar = any("\u0600" <= c <= "\u06FF" for c in question)
            return {
                "question": question,
                "sql": "",
                "results": [],
                "report": (
                    f"حدث خطأ في مسار LangGraph: {e}"
                    if is_ar
                    else f"LangGraph orchestration failed: {e}"
                ),
                "chart_suggestion": {},
                "success": False,
                "error": str(e),
                "error_type": "orchestrator_failure",
                "orchestrator": "langgraph",
                "attempted_sql": "",
                "warnings": [],
                "suggestions": [],
                "intent": "data_query",
                "timings_ms": {
                    "total_request_time_ms": round((time.perf_counter() - req_start) * 1000, 2),
                },
            }

    async def _run_service_pipeline(
        self,
        question: str,
        db: Session,
        memory=None,
        conversation_history: str = "",
        *args,
        **kwargs,
    ) -> dict[str, Any]:
        """Backward-compatible wrapper delegating to the single canonical LangGraph orchestrator."""
        import time
        req_start = time.perf_counter()
        if memory is None:
            memory = memory_manager.get_memory()
            conversation_history = memory.get_history_text()
        return await self._run_graph_pipeline(question, db, memory, conversation_history, req_start)

    async def ask(self, question: str, db: Session, session_id: str | None = None) -> dict[str, Any]:
        """
        Process a natural language question and return an analyst report.

        Routes through the single canonical LangGraph orchestrator.
        """
        result: dict[str, Any] = {
            "question": question,
            "sql": "",
            "results": [],
            "report": "",
            "chart_suggestion": {},
            "success": False,
            "error": None,
            "attempted_sql": "",
            "error_type": None,
            "warnings": [],
            "suggestions": [],
            "intent": "database",
        }

        import time
        req_start = time.perf_counter()
        timings_ms: dict[str, float] = {}

        if not question or not question.strip():
            result["error"] = "Question cannot be empty."
            result["report"] = "Please provide a question to analyze."
            timings_ms["total_request_time_ms"] = round((time.perf_counter() - req_start) * 1000, 2)
            result["timings_ms"] = timings_ms
            return result

        memory = memory_manager.get_memory(session_id)
        conversation_history = memory.get_history_text()

        t0 = time.perf_counter()
        db_ctx = self.schema_service.get_database_context()
        full_schema = db_ctx.schema
        catalog = db_ctx.catalog
        lookup_ms = (time.perf_counter() - t0) * 1000
        timings_ms["schema_cache_lookup_ms"] = round(lookup_ms, 2)
        timings_ms["schema_discovery_ms"] = 0.0
        timings_ms["catalog_lookup_build_ms"] = 0.0

        t0 = time.perf_counter()
        query_spec = await self.query_spec_builder.build_spec_async(
            question=question,
            db_ctx=db_ctx,
            conversation_history=conversation_history,
            catalog=catalog,
        )
        timings_ms["query_understanding_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        result["understanding_source"] = query_spec.source

        if query_spec.route == ExecutionRoute.CONVERSATION:
            conversation_report = query_spec.off_topic_response
            if not conversation_report:
                is_ar = any("\u0600" <= c <= "\u06FF" for c in question)
                conversation_report = (
                    "أنا مساعد متخصص في استعلام وتحليل قواعد البيانات. يمكنني مساعدتك في استعراض الجداول، حساب المؤشرات، وكتابة استعلامات SQL. يرجى توجيه سؤالك حول قاعدة البيانات أو البيانات المتصلة."
                    if is_ar else
                    "I am specialized in database analysis and querying. I can help you explore tables, compute metrics, write SQL queries, or generate data reports. Please ask a question related to your database or data."
                )
            memory.add_turn(question, "", conversation_report, "conversation")
            result["intent"] = "conversation"
            result["report"] = conversation_report
            result["success"] = True
            timings_ms["total_request_time_ms"] = round((time.perf_counter() - req_start) * 1000, 2)
            result["timings_ms"] = timings_ms
            return result

        if query_spec.route == ExecutionRoute.SCHEMA:
            schema_resp = await self.schema_explorer.handle_schema_exploration(question)
            if schema_resp:
                schema_resp["intent"] = "schema"
                memory.add_turn(question, schema_resp.get("sql", ""), schema_resp.get("report", ""), "schema")
                timings_ms["total_request_time_ms"] = round((time.perf_counter() - req_start) * 1000, 2)
                schema_resp["timings_ms"] = timings_ms
                return schema_resp

        if query_spec.requires_clarification:
            clarification_report = query_spec.clarification_prompt or (
                "Your question matches more than one table or semantic target. Please clarify which one you mean."
            )
            memory.add_turn(question, "", clarification_report, "database")
            result["intent"] = "clarification"
            result["report"] = clarification_report
            result["suggestions"] = query_spec.ambiguity_candidates
            result["error_type"] = "ambiguity"
            result["success"] = True
            if query_spec.ambiguity_evidence:
                result["warnings"].append(query_spec.ambiguity_evidence)
            timings_ms["total_request_time_ms"] = round((time.perf_counter() - req_start) * 1000, 2)
            result["timings_ms"] = timings_ms
            return result

        result["intent"] = "data_query"

        return await self._run_graph_pipeline(question, db, memory, conversation_history, req_start)
