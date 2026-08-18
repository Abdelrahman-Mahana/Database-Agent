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
from app.semantic.query_spec_builder import QuerySpecBuilder
from app.semantic.models import IntentType, ExecutionRoute, QuerySpec
from app.semantic.decision import DecisionLayer
from app.schema_catalog.catalog_builder import CatalogBuilder
from app.utils.cost_router import should_use_self_consistency, choose_sql_generation_tier
from app.config.settings import settings
from app.security.cost_guard import check_query_cost
from app.security.data_masking import mask_sensitive_columns

# --- Tunables -----------------------------------------------------------
LLM_TEMPERATURE = 0.1          # low temperature: we want deterministic, correct SQL
MAX_FIX_ATTEMPTS = getattr(settings, "max_fix_attempts", 1)  # bounded auto-repair attempts
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
    
    ARCHITECTURAL NOTE:
    This class contains the primary, battle-tested, production-ready linear pipeline (`ask()`).
    It executes steps synchronously in a fixed sequence. A secondary, experimental execution 
    path exists in `app.agents.graph_orchestrator` that uses LangGraph for more complex routing. 
    Both paths utilize the exact same underlying engines (SQLGenerator, SchemaGroundingEngine, etc.).
    The LangGraph path is only engaged if `settings.use_langgraph_orchestrator` is True.
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
        # Unified QuerySpec Builder (consolidates Intent + Semantics + Planning)
        self.query_spec_builder = QuerySpecBuilder(self.fast_llm)
        self.decision_layer = DecisionLayer(self.fast_llm)
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

        # Step 0: Decision Layer — no schema, no DB query, no SQL.
        t0 = time.perf_counter()
        decision = await self.decision_layer.decide(question, conversation_history)
        timings_ms["decision_layer_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        result["intent"] = decision.intent.value
        result["decision"] = {
            "route": decision.route.value,
            "confidence": decision.confidence,
            "needs_database": decision.needs_database,
            "needs_schema": decision.needs_schema,
            "needs_sql": decision.needs_sql,
            "needs_clarification": decision.needs_clarification,
            "reason": decision.reason,
        }

        if decision.needs_clarification:
            clarification = decision.clarification_question
            if not clarification:
                clarification = (
                    "ممكن توضح لي تقصد أنهي جزء بالضبط؟"
                    if any("\u0600" <= c <= "\u06FF" for c in question)
                    else "Could you clarify what you mean?"
                )
            memory.add_turn(question, "", clarification, "clarify")
            result["intent"] = "clarify"
            result["report"] = clarification
            result["success"] = True
            result["timings_ms"] = {**timings_ms, "total_request_time_ms": round((time.perf_counter() - req_start) * 1000, 2)}
            return result

        if decision.route == ExecutionRoute.CONVERSATION:
            conversation_report = await self.report_service.generate_conversational_response(
                question=question,
                conversation_history=conversation_history,
                database_context="Database access was intentionally skipped for this message.",
            )
            memory.add_turn(question, "", conversation_report, "conversation")
            result["intent"] = "conversation"
            result["report"] = conversation_report
            result["success"] = True
            result["timings_ms"] = {**timings_ms, "total_request_time_ms": round((time.perf_counter() - req_start) * 1000, 2)}
            return result

        # Schema is loaded only after the decision layer has determined that
        # database metadata or row-level data is actually relevant.
        t0 = time.perf_counter()
        db_ctx = self.schema_service.get_database_context()
        full_schema = db_ctx.schema
        catalog = db_ctx.catalog
        timings_ms["schema_cache_lookup_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        timings_ms["schema_discovery_ms"] = 0.0
        timings_ms["catalog_lookup_build_ms"] = 0.0

        # Semantic QuerySpec now runs only for database-backed actions.
        t0 = time.perf_counter()
        query_spec = self.query_spec_builder.build_spec(
            question=question,
            schema=full_schema,
            conversation_history=conversation_history,
            catalog=catalog,
            route_override=decision.route,
        )
        timings_ms["query_understanding_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        if decision.route == ExecutionRoute.SCHEMA:
            schema_resp = self.schema_explorer.handle_schema_exploration(question)
            if schema_resp:
                schema_resp["intent"] = "schema"
                memory.add_turn(question, schema_resp.get("sql", ""), schema_resp.get("report", ""), "schema")
                timings_ms["total_request_time_ms"] = round((time.perf_counter() - req_start) * 1000, 2)
                schema_resp["timings_ms"] = timings_ms
                return schema_resp

        result["intent"] = "data_query"

        # Phase 2 (rebuild plan): try the LangGraph agentic orchestrator when enabled
        if settings.use_langgraph_orchestrator:
            try:
                from app.agents.graph_orchestrator import run_graph_ask
                return await run_graph_ask(self, question, db, memory, conversation_history)
            except Exception as graph_err:
                logger.exception(
                    "LangGraph orchestration failed, falling back to the linear pipeline: %s", graph_err
                )

        try:
            # Step 1.1: DB connection acquisition
            t0 = time.perf_counter()
            try:
                from sqlalchemy import text
                db.execute(text("SELECT 1"))
            except Exception:
                pass
            timings_ms["db_connection_acquisition_ms"] = round((time.perf_counter() - t0) * 1000, 2)

            # Step 1.2: Build Grounded minimal schema subset using unified QuerySpec
            grounded_schema = await self.schema_grounding_engine.build_grounded_schema_async(
                schema=full_schema,
                query_understanding=query_spec,
                question=question,
                analysis_type=query_spec.analysis_type,
                catalog=catalog,
            )
            schema_text = grounded_schema.schema_text

            if getattr(grounded_schema, "fallback_used", False):
                warn_msg = (
                    "ما زال يتم قراءة وتحليل هيكل قاعدة البيانات. قد تكون هذه الإجابة غير دقيقة مؤقتًا."
                    if any("\u0600" <= c <= "\u06FF" for c in question) else
                    "Database schema profiling is still in progress. This answer may be inaccurate temporarily."
                )
                result["warnings"].append(warn_msg)

            for k, v in grounded_schema.timings_ms.items():
                timings_ms[k] = round(v, 2)

            total_tables = getattr(db_ctx, "total_tables", len(full_schema))
            total_columns = getattr(db_ctx, "total_columns", 0) or sum(len(info.get("columns", [])) for info in full_schema.values())
            retrieved_tables = len(grounded_schema.retrieved_seed_tables)
            retrieved_columns = sum(len(full_schema[t].get("columns", [])) for t in grounded_schema.retrieved_seed_tables if t in full_schema)
            grounded_tables = len(grounded_schema.selected_tables)
            grounded_columns = sum(len(cols) for cols in grounded_schema.selected_columns.values())
            schema_text_len = len(schema_text)

            schema_metrics = {
                "total_tables": total_tables,
                "total_columns": total_columns,
                "retrieved_tables": retrieved_tables,
                "retrieved_columns": retrieved_columns,
                "grounded_tables": grounded_tables,
                "grounded_columns": grounded_columns,
                "final_schema_tables": grounded_tables,
                "final_schema_columns": grounded_columns,
                "estimated_schema_chars": schema_text_len,
                "estimated_prompt_chars": schema_text_len + len(question) + 500,
                "estimated_token_count": schema_text_len // 4,
            }
            result["schema_metrics"] = schema_metrics

            # Classify analysis type
            analysis_type = query_spec.analysis_type
            result["analysis_type"] = analysis_type.value if hasattr(analysis_type, "value") else str(analysis_type)

            # Step 2: Generate SQL via LLM (Primary Single-Pass SQL path)
            grounded_tables_count = len(grounded_schema.selected_tables) if grounded_schema else 1
            has_grouping = len(query_spec.dimensions) > 0 if query_spec else False
            use_voting = should_use_self_consistency(
                question, analysis_type, schema_token_estimate=schema_text_len // 4
            )

            use_fast = choose_sql_generation_tier(
                question, analysis_type, query_spec.confidence,
                grounded_table_count=grounded_tables_count, has_grouping=has_grouping
            )

            t0 = time.perf_counter()
            sql = await self.sql_generator.generate_sql(
                question, schema_text, db, conversation_history,
                use_self_consistency=use_voting, use_fast_model=(use_fast == "fast"),
            )
            timings_ms["sql_generation_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            result["sql"] = sql

            # Short-circuit if the model determined the question is out of scope
            reason = self.sql_generator.unanswerable_reason(sql)
            if reason:
                logger.info("Question flagged UNANSWERABLE: %s", reason)
                result["sql"] = ""
                result["report"] = await self.report_service.generate_no_answer_response(
                    question=question,
                    situation="This question cannot be answered using the current database schema.",
                    reason=reason,
                    table_names=list(full_schema.keys()),
                )
                result["success"] = True
                memory.add_turn(question, sql, f"Unanswerable: {reason}", "database")

                timings_ms["total_request_time_ms"] = round((time.perf_counter() - req_start) * 1000, 2)
                result["timings_ms"] = timings_ms
                return result

            # Step 3: Validate SQL safety
            t0 = time.perf_counter()
            validation = validate_sql(sql)
            if not validation["valid"]:
                timings_ms["sql_validation_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                result["attempted_sql"] = sql
                result["error_type"] = validation.get("query_type", "safety")
                result["error"] = validation["reason"]
                result["report"] = await self.report_service.generate_no_answer_response(
                    question=question,
                    situation="The generated query could not be safely executed.",
                    reason=validation["reason"],
                    table_names=list(full_schema.keys()),
                )
                timings_ms["total_request_time_ms"] = round((time.perf_counter() - req_start) * 1000, 2)
                result["timings_ms"] = timings_ms
                return result

            # Step 3.5: Static cost pre-check (Phase 5)
            if settings.enable_cost_guard:
                try:
                    cost_check = check_query_cost(sql, catalog, settings.cost_guard_max_unfiltered_rows)
                except Exception as cost_err:
                    cost_check = None
                    logger.debug("Cost guard check skipped: %s", cost_err)
                if cost_check is not None and not cost_check.allowed:
                    timings_ms["sql_validation_ms"] = round((time.perf_counter() - t0) * 1000, 2)
                    result["attempted_sql"] = sql
                    result["error_type"] = "cost_guard"
                    result["error"] = cost_check.reason
                    result["report"] = await self.report_service.generate_no_answer_response(
                        question=question,
                        situation="The query was blocked before execution because it would scan an unusually large amount of data.",
                        reason=cost_check.reason,
                        table_names=list(full_schema.keys()),
                    )
                    timings_ms["total_request_time_ms"] = round((time.perf_counter() - req_start) * 1000, 2)
                    result["timings_ms"] = timings_ms
                    return result

            timings_ms["sql_validation_ms"] = round((time.perf_counter() - t0) * 1000, 2)

            # Step 4: Execute, auto-repairing on failure (bounded retries)
            t0 = time.perf_counter()
            gen_meta = getattr(self.sql_generator, "last_generation_meta", {})
            initial_tier = gen_meta.get("sql_generation_tier", "primary")
            sql_cache_hit = gen_meta.get("sql_cache_hit", False)

            rows, final_sql, exec_error, error_type, suggestions = await self.sql_generator.execute_with_repair(
                question=question, schema_text=schema_text, sql=sql, db=db, max_fix_attempts=MAX_FIX_ATTEMPTS,
                initial_tier=initial_tier, sql_cache_hit=sql_cache_hit,
            )
            timings_ms["sql_execution_ms"] = round((time.perf_counter() - t0) * 1000, 2)

            exec_meta = getattr(self.sql_generator, "last_execution_meta", {})
            for k in ("sql_generation_tier", "sql_final_tier", "sql_repair_attempts", "sql_repair_success", "sql_cache_hit"):
                val = exec_meta.get(k)
                result[k] = val

            timings_ms["sql_repair_attempts"] = float(exec_meta.get("sql_repair_attempts", 0))
            timings_ms["sql_cache_hit"] = 1.0 if exec_meta.get("sql_cache_hit") else 0.0
            timings_ms["sql_repair_success"] = 1.0 if exec_meta.get("sql_repair_success") else 0.0

            # Fallback to Planner if single-SQL execution failed on complex multi-step question
            if exec_error is not None:
                if analysis_type in COMPLEX_ANALYSIS_TYPES or query_spec.requires_multi_step:
                    logger.info("Single-SQL failed for complex analysis. Triggering Planner as FALLBACK...")
                    try:
                        planner = Planner(self.primary_llm, self.fast_llm)
                        plan_steps = await planner.decompose_question(question, schema_text, conversation_history)
                        if plan_steps and len(plan_steps) >= 2:
                            plan_result = await planner.execute_plan(
                                question=question,
                                plan_steps=plan_steps,
                                schema_text=schema_text,
                                db=db,
                                conversation_history=conversation_history,
                                sql_generator=self.sql_generator,
                                report_service=self.report_service,
                                memory=memory
                            )
                            if plan_result and plan_result.get("success"):
                                timings_ms["total_request_time_ms"] = round((time.perf_counter() - req_start) * 1000, 2)
                                plan_result["timings_ms"] = timings_ms
                                plan_result["schema_metrics"] = schema_metrics
                                return plan_result
                    except Exception as plan_err:
                        logger.warning("Planner fallback execution failed: %s", plan_err)

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
                timings_ms["total_request_time_ms"] = round((time.perf_counter() - req_start) * 1000, 2)
                result["timings_ms"] = timings_ms
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
            t0 = time.perf_counter()
            if rows:
                try:
                    analytics_result = self.analytics_engine.analyze(rows)
                    insight_result = self.insight_engine.generate_insights(analytics_result)
                except Exception as analytics_err:
                    logger.warning("Analytics/Insight pipeline execution failed gracefully: %s", analytics_err)
            timings_ms["analytics_ms"] = round((time.perf_counter() - t0) * 1000, 2)

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
                timings_ms["total_request_time_ms"] = round((time.perf_counter() - req_start) * 1000, 2)
                result["timings_ms"] = timings_ms
                return result

            truncated = len(rows) > MAX_ROWS_FOR_LLM
            rows_for_llm = rows[:MAX_ROWS_FOR_LLM] if truncated else rows

            t0 = time.perf_counter()
            report = await self.report_service.generate_conversational_data_response(
                question=question,
                sql=final_sql,
                results=rows_for_llm,
                conversation_history=conversation_history,
                analytics_result=analytics_result,
                insight_result=insight_result,
            )
            chart = await self.report_service.suggest_chart(
                question=question,
                sql=final_sql,
                results=rows_for_llm,
                analytics_result=analytics_result,
                insight_result=insight_result,
            )
            step_duration = round((time.perf_counter() - t0) * 1000, 2)
            timings_ms["report_generation_ms"] = step_duration
            timings_ms["chart_suggestion_ms"] = 0.0

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

        timings_ms["total_request_time_ms"] = round((time.perf_counter() - req_start) * 1000, 2)
        result["timings_ms"] = timings_ms
        from app.utils.token_tracker import get_llm_trace
        trace = get_llm_trace()
        result["llm_trace"] = trace
        result["llm_call_count"] = len(trace)
        logger.info(
            "Stage timings (ms): %s | Schema metrics: %s | LLM calls: %d",
            timings_ms, result.get("schema_metrics", {}), len(trace),
        )
        return result
