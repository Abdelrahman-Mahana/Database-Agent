"""Analyst Agent — orchestrates schema reading → SQL generation → execution → report."""
from typing import Any
from sqlalchemy.orm import Session
from loguru import logger

from app.llm.model import get_llm_client, get_langchain_llm
from app.services.sql_service import SchemaService
from app.services.report_service import ReportService
from app.services.memory import memory_manager
from app.utils.validator import validate_sql
from app.utils.text_processor import build_result_summary, classify_analysis_type, COMPLEX_ANALYSIS_TYPES, is_complex_query

from app.agents.intent_classifier import IntentClassifier
from app.agents.schema_explorer import SchemaExplorer
from app.agents.sql_generator import SQLGenerator
from app.agents.planner import Planner
from app.schema_grounding.grounding_engine import SchemaGroundingEngine
from app.analytics import AnalyticsEngine, InsightEngine
from app.semantic.hybrid import HybridQueryUnderstander
from app.semantic.synonyms import resolve_synonyms
from app.schema_catalog.catalog_builder import CatalogBuilder
from app.utils.cost_router import should_use_self_consistency, choose_sql_generation_tier
from app.core.config import settings
from app.security.cost_guard import check_query_cost
from app.security.data_masking import mask_sensitive_columns

# --- Tunables -----------------------------------------------------------
LLM_TEMPERATURE = 0.1          # low temperature: we want deterministic, correct SQL
MAX_FIX_ATTEMPTS = 2           # how many times we try to auto-repair a failing query
MAX_ROWS_FOR_LLM = 200         # cap rows sent to the report/chart LLM calls (cost + context safety)


class AnalystAgent:
    """
    End-to-end agent that:
    1. Reads the database schema
    2. Generates SQL from natural language
    3. Validates SQL safety (SELECT-only)
    4. Executes SQL, auto-repairing on failure (bounded retries)
    5. Generates an analyst report
    6. Suggests chart options
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

        # Components
        self.intent_classifier = IntentClassifier(self.fast_llm)
        self.schema_explorer = SchemaExplorer()
        self.sql_generator = SQLGenerator(self.primary_llm, self.self_consistency_llm, fast_llm=self.fast_llm)
        self.planner = Planner(self.primary_llm, self.fast_llm)
        # Phase 1 (rebuild plan): understanding is now a feature-flagged
        # LLM-reasoning node with the original regex parser as an automatic
        # fallback (USE_LLM_UNDERSTANDING env var). See app/semantic/hybrid.py.
        self.query_understander = HybridQueryUnderstander(self.fast_llm)
        self.analytics_engine = AnalyticsEngine()
        self.insight_engine = InsightEngine()
        # Phase 2 (rebuild plan): compiled lazily on first use, only if
        # USE_LANGGRAPH_ORCHESTRATOR=true. See app/agents/graph_orchestrator.py.
        self._graph = None

    def get_or_build_graph(self):
        """Lazily build+cache the LangGraph orchestrator for this agent instance."""
        if self._graph is None:
            from app.agents.graph_orchestrator import build_analyst_graph
            self._graph = build_analyst_graph(self)
        return self._graph

    async def ask(self, question: str, db: Session, session_id: str | None = None) -> dict[str, Any]:
        """
        Process a natural language question and return an analyst report.

        Returns:
            {
                "question": str,
                "sql": str,
                "results": list[dict],
                "report": str,
                "chart_suggestion": dict,
                "success": bool,
                "error": str | None,
            }
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
            "suggestions": [],
            "intent": "database",
        }

        if not question or not question.strip():
            result["error"] = "Question cannot be empty."
            result["report"] = "Please provide a question to analyze."
            return result

        memory = memory_manager.get_memory(session_id)
        conversation_history = memory.get_history_text()

        # Step 0: Check for schema exploration queries (no LLM, offline resolve)
        if self.schema_explorer.is_schema_query(question):
            schema_resp = self.schema_explorer.handle_schema_exploration(question)
            if schema_resp:
                schema_resp["intent"] = "schema"
                memory.add_turn(question, schema_resp.get("sql", ""), schema_resp.get("report", ""), "schema")
                return schema_resp

        # Step 0.5: Classify user intent (database vs off-topic vs schema fallback)
        intent_info = await self.intent_classifier.classify_intent(question, conversation_history)
        intent = intent_info.get("intent", "database")
        result["intent"] = intent

        if intent == "off_topic":
            off_topic_report = await self.intent_classifier.generate_off_topic_response(question)
            memory.add_turn(question, "", off_topic_report, "off_topic")
            result["report"] = off_topic_report
            result["success"] = True
            return result
        elif intent == "schema":
            schema_resp = self.schema_explorer.handle_schema_exploration(question)
            if schema_resp:
                schema_resp["intent"] = "schema"
                memory.add_turn(question, schema_resp.get("sql", ""), schema_resp.get("report", ""), "schema")
                return schema_resp
            result["intent"] = "database"

        # Phase 2 (rebuild plan): try the LangGraph agentic orchestrator when
        # enabled. Falls back to the untouched linear pipeline below on ANY
        # failure - including langgraph not being installed - so flipping
        # this flag can never take the app down.
        if settings.use_langgraph_orchestrator:
            try:
                from app.agents.graph_orchestrator import run_graph_ask
                return await run_graph_ask(self, question, db, memory, conversation_history)
            except Exception as graph_err:
                logger.exception(
                    "LangGraph orchestration failed, falling back to the linear pipeline: %s", graph_err
                )

        try:
            # Step 1: Get grounded minimal schema subset
            full_schema = self.schema_service.get_schema()
            query_understanding = await self.query_understander.understand(
                question, full_schema, conversation_history
            )
            logger.debug(
                "Query understanding source=%s analysis_type=%s confidence=%.2f",
                query_understanding.source, query_understanding.analysis_type, query_understanding.confidence,
            )

            # Phase 2: resolve business-language synonyms (e.g. "الإيراد" ->
            # Orders.Total) against the persisted glossary, if one has been
            # built for this DB. Pure dict lookups — zero extra LLM cost.
            # Safe no-op if no catalog/glossary exists yet for this database.
            catalog = None
            try:
                catalog = self.catalog_builder.get_or_build()
                query_understanding = resolve_synonyms(question, catalog, query_understanding)
            except Exception as catalog_err:
                logger.debug("Schema catalog lookup skipped: %s", catalog_err)

            grounded_schema = self.schema_grounding_engine.build_grounded_schema(
                schema=full_schema,
                query_understanding=query_understanding,
                question=question,
                analysis_type=query_understanding.analysis_type,
                catalog=catalog,
            )
            schema_text = grounded_schema.schema_text

            # Classify analysis type & determine if Planner is required
            analysis_type = query_understanding.analysis_type
            result["analysis_type"] = analysis_type.value if hasattr(analysis_type, "value") else str(analysis_type)
            # Trigger the multi-step Planner on EITHER signal: the legacy
            # keyword-derived analysis_type (kept as a safety net so behavior
            # never regresses when running on the regex path) OR the LLM
            # understanding node's own reasoned judgment that this question
            # needs decomposition (only set when USE_LLM_UNDERSTANDING=true
            # and the LLM path was actually used - see semantic/hybrid.py).
            if analysis_type in COMPLEX_ANALYSIS_TYPES or query_understanding.requires_multi_step:
                plan_steps = await self.planner.decompose_question(question, schema_text, conversation_history)
                if plan_steps and len(plan_steps) >= 2:
                    plan_result = await self.planner.execute_plan(
                        question=question,
                        plan_steps=plan_steps,
                        schema_text=schema_text,
                        db=db,
                        conversation_history=conversation_history,
                        sql_generator=self.sql_generator,
                        report_service=self.report_service,
                        memory=memory
                    )
                    if plan_result:
                        return plan_result

            # Step 2: Generate SQL via LLM (Fallback / Single-step path)
            # Phase 4: decide per-question (not globally) whether the extra
            # cost of self-consistency voting is worth it for this question.
            use_voting = should_use_self_consistency(question, analysis_type)
            use_fast = choose_sql_generation_tier(question, analysis_type, query_understanding.confidence)
            sql = await self.sql_generator.generate_sql(
                question, schema_text, db, conversation_history,
                use_self_consistency=use_voting, use_fast_model=(use_fast == "fast"),
            )
            result["sql"] = sql

            # Short-circuit if the model determined the question is out of scope
            reason = self.sql_generator.unanswerable_reason(sql)
            if reason:
                logger.info("Question flagged UNANSWERABLE: %s", reason)
                result["report"] = await self.report_service.generate_no_answer_response(
                    question=question,
                    situation="This question cannot be answered using the current database schema.",
                    reason=reason,
                    table_names=list(full_schema.keys()),
                )
                result["success"] = True
                memory.add_turn(question, sql, f"Unanswerable: {reason}", "database")
                return result

            # Step 3: Validate SQL safety
            validation = validate_sql(sql)
            if not validation["valid"]:
                result["attempted_sql"] = sql
                result["error_type"] = validation.get("query_type", "safety")
                result["error"] = validation["reason"]
                result["report"] = await self.report_service.generate_no_answer_response(
                    question=question,
                    situation="The generated query could not be safely executed.",
                    reason=validation["reason"],
                    table_names=list(full_schema.keys()),
                )
                return result

            # Step 3.5: Static cost pre-check (Phase 5) — catches unfiltered,
            # unlimited scans of very large tables before they ever hit the
            # database, using row counts already captured in the schema
            # catalog. Fails open (allows) when it can't reason about cost.
            if settings.enable_cost_guard:
                try:
                    cost_check = check_query_cost(sql, catalog, settings.cost_guard_max_unfiltered_rows)
                except Exception as cost_err:
                    cost_check = None
                    logger.debug("Cost guard check skipped: %s", cost_err)
                if cost_check is not None and not cost_check.allowed:
                    result["attempted_sql"] = sql
                    result["error_type"] = "cost_guard"
                    result["error"] = cost_check.reason
                    result["report"] = await self.report_service.generate_no_answer_response(
                        question=question,
                        situation="The query was blocked before execution because it would scan an unusually large amount of data.",
                        reason=cost_check.reason,
                        table_names=list(full_schema.keys()),
                    )
                    return result

            # Step 4: Execute, auto-repairing on failure (bounded retries)
            rows, final_sql, exec_error, error_type, suggestions = await self.sql_generator.execute_with_repair(
                question=question, schema_text=schema_text, sql=sql, db=db, max_fix_attempts=MAX_FIX_ATTEMPTS
            )
            if exec_error is not None:
                result["attempted_sql"] = final_sql
                result["error_type"] = error_type
                result["error"] = exec_error
                result["suggestions"] = suggestions

                if suggestions:
                    suggestion_str = " or ".join(f"'{s}'" for s in suggestions)
                    reason_text = f"{exec_error}. Closest matching names available: {suggestion_str}."
                else:
                    reason_text = exec_error
                result["report"] = await self.report_service.generate_no_answer_response(
                    question=question,
                    situation="The query failed to execute even after attempting to automatically repair it.",
                    reason=reason_text,
                    table_names=list(full_schema.keys()),
                )
                return result

            result["sql"] = final_sql

            # Phase 5: mask sensitive columns BEFORE rows reach analytics,
            # the report-writing LLM call, or memory — so a column like
            # ssn/password/api_key never gets echoed into a generated report
            # even if the query happened to select it (e.g. via SELECT *).
            if settings.enable_data_masking and rows:
                try:
                    rows, masked_cols = mask_sensitive_columns(rows, settings.extra_masked_column_patterns)
                    if masked_cols:
                        logger.info("Masked sensitive columns in results: %s", masked_cols)
                except Exception as mask_err:
                    logger.debug("Data masking skipped: %s", mask_err)

            result["results"] = rows

            # Step 4.5: Run AnalyticsEngine & InsightEngine deterministic pipeline
            analytics_result = None
            insight_result = None
            if rows:
                try:
                    analytics_result = self.analytics_engine.analyze(rows)
                    insight_result = self.insight_engine.generate_insights(analytics_result)
                except Exception as analytics_err:
                    logger.warning("Analytics/Insight pipeline execution failed gracefully: %s", analytics_err)

            # Step 5: Generate report
            if not rows:
                result["report"] = await self.report_service.generate_no_answer_response(
                    question=question,
                    situation="The query ran successfully but returned no matching rows.",
                    reason="No records matched the filters implied by the question.",
                    table_names=list(full_schema.keys()),
                )
                result["success"] = True
                memory.add_turn(question, final_sql, "No rows returned.", "database")
                return result

            truncated = len(rows) > MAX_ROWS_FOR_LLM
            rows_for_llm = rows[:MAX_ROWS_FOR_LLM] if truncated else rows

            report = await self.report_service.generate_report(
                question, final_sql, rows_for_llm,
                analytics_result=analytics_result,
                insight_result=insight_result,
                require_verification=(analysis_type in COMPLEX_ANALYSIS_TYPES),
            )
            if truncated:
                if any("\u0600" <= c <= "\u06FF" for c in question):
                    report += (
                        f"\n\n*ملاحظة: هذا التحليل مبني على أول {MAX_ROWS_FOR_LLM} "
                        f"صف من إجمالي {len(rows)} صف مُسترجع.*"
                    )
                else:
                    report += (
                        f"\n\n*Note: this analysis is based on the first {MAX_ROWS_FOR_LLM} "
                        f"of {len(rows)} returned rows.*"
                    )
            result["report"] = report

            chart = await self.report_service.suggest_chart(
                question, final_sql, rows_for_llm,
                analytics_result=analytics_result,
                insight_result=insight_result
            )
            result["chart_suggestion"] = chart

            memory.add_turn(question, final_sql, build_result_summary(rows), "database")
            result["success"] = True

        except Exception as e:
            logger.exception("AnalystAgent.ask failed for question=%r", question)
            result["error"] = str(e)
            if any("\u0600" <= c <= "\u06FF" for c in question):
                result["report"] = f"حدث خطأ أثناء معالجة طلبك: {e}"
            else:
                result["report"] = f"I encountered an error: {e}"

        return result