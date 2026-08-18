"""LangGraph Agentic Orchestrator (Rebuild Plan — Phase 2).

ARCHITECTURAL NOTE:
This module provides an experimental, feature-flagged (`use_langgraph_orchestrator`) 
execution path. It is used for A/B testing graph-based execution against the stable 
linear pipeline found in `app.agents.analyst_agent`. 

Replaces the linear if/else step-by-step method body of `AnalystAgent.ask`
with a `StateGraph` — but does NOT reimplement any business logic. Every
node here is a thin wrapper around the exact same components/methods the
linear pipeline already calls (`SchemaGroundingEngine`, `Planner`,
`SQLGenerator`, `ReportService`, `AnalyticsEngine`, ...). This is the
"existing classes = ready-made Tools" approach from the roadmap: wrap, don't
rewrite.

What actually changes vs the linear pipeline:
- Control flow is expressed as graph edges (some conditional) instead of
  nested if/else + early `return`.
- ONE new capability: a bounded reflect-and-retry loop. If SQL execution
  fails even after `execute_with_repair`'s own bounded auto-repair, the
  linear pipeline always gives up and reports "no answer". This graph gets
  exactly one extra chance to re-run the *understanding* step with a hint
  about what went wrong, in case the root cause was a misidentified
  table/column rather than a bad SQL statement — then retries generation.
  Bounded to a single retry (`state["retried"]`) so this can never loop.

This module is imported lazily (only when `settings.use_langgraph_orchestrator`
is true) so the app keeps working unmodified if `langgraph` isn't installed.

Safety/architecture boundaries preserved exactly as in the linear pipeline:
- SQL safety validation (`validate_sql`, sqlglot AST) is untouched and still
  runs as its own deterministic step - the graph never skips or reinterprets it.
- Cost guard, data masking, and analytics are still fully deterministic and
  still run in the same relative order.
"""
from typing import Any, Optional, TypedDict

from loguru import logger
from langgraph.graph import StateGraph, END

from app.utils.validator import validate_sql
from app.utils.text_processor import build_result_summary, COMPLEX_ANALYSIS_TYPES
from app.semantic.synonyms import resolve_synonyms
from app.utils.cost_router import should_use_self_consistency, choose_sql_generation_tier
from app.config.settings import settings
from app.security.cost_guard import check_query_cost
from app.security.data_masking import mask_sensitive_columns
from app.semantic.models import ExecutionRoute

MAX_FIX_ATTEMPTS = getattr(settings, "max_fix_attempts", 1)
MAX_ROWS_FOR_LLM = 200


class AgentState(TypedDict, total=False):
    question: str
    db: Any
    memory: Any
    conversation_history: str
    full_schema: dict
    catalog: Any
    query_understanding: Any
    grounded_schema: Any
    schema_text: str
    analysis_type: Any
    sql: str
    rows: list
    final_sql: str
    exec_error: Optional[str]
    error_type: Optional[str]
    suggestions: list
    analytics_result: Any
    insight_result: Any
    retried: bool
    retry_hint: str
    plan_completed: bool
    result: dict


def _base_result(question: str) -> dict:
    return {
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
        "intent": "data_query",
    }


def build_analyst_graph(agent) -> "StateGraph":
    """Build (but do not compile) the StateGraph for a given AnalystAgent instance.

    `agent` is the already-constructed `AnalystAgent` - we reuse its
    components (schema_service, query_understander, planner, sql_generator,
    report_service, analytics_engine, insight_engine, catalog_builder)
    verbatim rather than constructing new ones, so behavior/config for each
    step is identical to the linear pipeline.
    """

    async def understand_node(state: AgentState) -> dict:
        import time
        question = state["question"]
        conversation_history = state["conversation_history"]
        result = state.get("result") or _base_result(question)
        if "timings_ms" not in result:
            result["timings_ms"] = {}

        # 1. DB Context & Schema Lookup (from in-RAM DatabaseContext)
        db_ctx = agent.schema_service.get_database_context()
        full_schema = db_ctx.schema
        catalog = db_ctx.catalog

        # 2. Single-pass Unified QuerySpecBuilder (< 0.15ms, 0 LLM calls)
        t_und_start = time.perf_counter()
        query_spec = agent.query_spec_builder.build_spec(
            question=question,
            schema=full_schema,
            conversation_history=conversation_history,
            catalog=catalog,
        )
        und_ms = (time.perf_counter() - t_und_start) * 1000
        result["timings_ms"]["query_understanding_ms"] = round(und_ms, 2)
        result["intent"] = query_spec.intent.value

        # Route first: conversation/general, schema/metadata, or real data query.
        if query_spec.route == ExecutionRoute.CONVERSATION:
            reply = query_spec.off_topic_response
            if not reply or query_spec.route_confidence < 0.9:
                reply = await agent.report_service.generate_conversational_response(
                    question=question,
                    conversation_history=conversation_history,
                    database_context="A database connection exists, but this request was classified as conversational/general.",
                )
            result["intent"] = "conversation"
            result["report"] = reply
            result["success"] = True
            state_result = {
                "result": result, "full_schema": full_schema, "catalog": catalog,
                "query_understanding": query_spec, "analysis_type": query_spec.analysis_type
            }
            return state_result

        if query_spec.route == ExecutionRoute.SCHEMA:
            schema_resp = agent.schema_explorer.handle_schema_exploration(question)
            if schema_resp:
                schema_resp["intent"] = "schema"
                state_result = {
                    "result": schema_resp, "full_schema": full_schema, "catalog": catalog,
                    "query_understanding": query_spec, "analysis_type": query_spec.analysis_type
                }
                return state_result

        result["intent"] = "data_query"

        return {
            "full_schema": full_schema,
            "query_understanding": query_spec,
            "catalog": catalog,
            "analysis_type": query_spec.analysis_type,
            "result": result,
        }

    def route_after_understand(state: AgentState) -> str:
        if state["result"].get("report"):
            return END
        return "ground_schema"

    async def ground_schema_node(state: AgentState) -> dict:
        query_understanding = state["query_understanding"]
        grounded_schema = await agent.schema_grounding_engine.build_grounded_schema_async(
            schema=state["full_schema"],
            query_understanding=query_understanding,
            question=state["question"],
            analysis_type=query_understanding.analysis_type,
            catalog=state.get("catalog"),
        )
        full_schema = state["full_schema"]
        total_tables = len(full_schema)
        total_columns = sum(len(info.get("columns", [])) for info in full_schema.values())
        grounded_tables = len(grounded_schema.selected_tables)
        grounded_columns = sum(len(cols) for cols in grounded_schema.selected_columns.values())
        schema_text_len = len(grounded_schema.schema_text)

        schema_metrics = {
            "total_tables": total_tables,
            "total_columns": total_columns,
            "retrieved_tables": len(grounded_schema.retrieved_seed_tables),
            "grounded_tables": grounded_tables,
            "grounded_columns": grounded_columns,
            "estimated_schema_chars": schema_text_len,
            "estimated_token_count": schema_text_len // 4,
        }
        result = state.get("result", {})
        result["schema_metrics"] = schema_metrics
        if "timings_ms" not in result:
            result["timings_ms"] = {}
        for k, v in grounded_schema.timings_ms.items():
            result["timings_ms"][k] = round(v, 2)

        return {"grounded_schema": grounded_schema, "schema_text": grounded_schema.schema_text, "result": result}

    def route_after_ground(state: AgentState) -> str:
        # Single-SQL First: Always attempt single-pass SQL generation first (1 LLM call)
        return "generate_sql"

    async def planner_fallback_node(state: AgentState) -> dict:
        """
        Planner invoked ONLY as a fallback when single-SQL execution fails after auto-repair.
        Reuses existing grounded schema without restarting the pipeline.
        """
        logger.info("Single-SQL execution failed, activating Planner multi-step fallback.")
        question = state["question"]
        schema_text = state["schema_text"]
        conversation_history = state["conversation_history"]

        plan_steps = await agent.planner.decompose_question(question, schema_text, conversation_history)
        if plan_steps and len(plan_steps) >= 2:
            plan_result = await agent.planner.execute_plan(
                question=question,
                plan_steps=plan_steps,
                schema_text=schema_text,
                db=state["db"],
                conversation_history=conversation_history,
                sql_generator=agent.sql_generator,
                report_service=agent.report_service,
                memory=state["memory"],
            )
            if plan_result and plan_result.get("success"):
                return {"result": plan_result, "plan_completed": True, "retried": True}

        return {"plan_completed": False, "retried": True}

    def route_after_planner_fallback(state: AgentState) -> str:
        return END if state.get("plan_completed") else "report_exec_error"

    async def generate_sql_node(state: AgentState) -> dict:
        import time
        question = state["question"]
        schema_text = state["schema_text"]
        analysis_type = state["analysis_type"]
        qu = state.get("query_understanding")
        grounded_tables_count = len(state["grounded_schema"].selected_tables) if state.get("grounded_schema") else 1
        has_grouping = len(qu.dimensions) > 0 if qu else False

        schema_token_estimate = len(schema_text) // 4 if schema_text else 0
        use_voting = should_use_self_consistency(
            question, analysis_type, schema_token_estimate=schema_token_estimate
        )

        use_fast = choose_sql_generation_tier(
            question, analysis_type, qu.confidence if qu else 1.0,
            grounded_table_count=grounded_tables_count, has_grouping=has_grouping
        )

        t0 = time.perf_counter()
        sql = await agent.sql_generator.generate_sql(
            question, schema_text, state["db"], state["conversation_history"],
            use_self_consistency=use_voting, use_fast_model=(use_fast == "fast"),
        )
        gen_ms = (time.perf_counter() - t0) * 1000

        result = state.get("result") or _base_result(question)
        if "timings_ms" not in result:
            result["timings_ms"] = {}
        result["timings_ms"]["sql_generation_ms"] = round(gen_ms, 2)
        result["sql"] = sql
        result["analysis_type"] = analysis_type.value if hasattr(analysis_type, "value") else str(analysis_type)

        reason = agent.sql_generator.unanswerable_reason(sql)
        if reason:
            logger.info("Question flagged UNANSWERABLE: %s", reason)
            result["sql"] = ""
            result["report"] = await agent.report_service.generate_no_answer_response(
                question=question,
                situation="This question cannot be answered using the current database schema.",
                reason=reason,
                table_names=list(state["full_schema"].keys()),
            )
            result["success"] = True
            state["memory"].add_turn(question, sql, f"Unanswerable: {reason}", "database")
            return {"sql": "", "result": result}

        return {"sql": sql, "result": result}

    def route_after_generate(state: AgentState) -> str:
        return END if state["result"].get("report") else "validate_sql"

    async def validate_sql_node(state: AgentState) -> dict:
        import time
        sql = state["sql"]
        result = state["result"]
        t0 = time.perf_counter()
        validation = validate_sql(sql)
        val_ms = (time.perf_counter() - t0) * 1000
        if "timings_ms" not in result:
            result["timings_ms"] = {}
        result["timings_ms"]["sql_validation_ms"] = round(val_ms, 2)

        if not validation["valid"]:
            result["attempted_sql"] = sql
            result["error_type"] = validation.get("query_type", "safety")
            result["error"] = validation["reason"]
            result["report"] = await agent.report_service.generate_no_answer_response(
                question=state["question"],
                situation="The generated query could not be safely executed.",
                reason=validation["reason"],
                table_names=list(state["full_schema"].keys()),
            )
        return {"result": result}

    def route_after_validate(state: AgentState) -> str:
        return END if state["result"].get("report") else "cost_guard"

    async def cost_guard_node(state: AgentState) -> dict:
        result = state["result"]
        if settings.enable_cost_guard:
            try:
                cost_check = check_query_cost(state["sql"], state.get("catalog"), settings.cost_guard_max_unfiltered_rows)
            except Exception as cost_err:
                cost_check = None
                logger.debug("Cost guard check skipped: %s", cost_err)
            if cost_check is not None and not cost_check.allowed:
                result["attempted_sql"] = state["sql"]
                result["error_type"] = "cost_guard"
                result["error"] = cost_check.reason
                result["report"] = await agent.report_service.generate_no_answer_response(
                    question=state["question"],
                    situation="The query was blocked before execution because it would scan an unusually large amount of data.",
                    reason=cost_check.reason,
                    table_names=list(state["full_schema"].keys()),
                )
        return {"result": result}

    def route_after_cost_guard(state: AgentState) -> str:
        return END if state["result"].get("report") else "execute"

    async def execute_node(state: AgentState) -> dict:
        import time
        t0 = time.perf_counter()
        gen_meta = getattr(agent.sql_generator, "last_generation_meta", {})
        initial_tier = gen_meta.get("sql_generation_tier", "primary")
        sql_cache_hit = gen_meta.get("sql_cache_hit", False)

        rows, final_sql, exec_error, error_type, suggestions = await agent.sql_generator.execute_with_repair(
            question=state["question"], schema_text=state["schema_text"], sql=state["sql"],
            db=state["db"], max_fix_attempts=MAX_FIX_ATTEMPTS,
            initial_tier=initial_tier, sql_cache_hit=sql_cache_hit,
        )
        exec_ms = (time.perf_counter() - t0) * 1000
        exec_meta = getattr(agent.sql_generator, "last_execution_meta", {})

        result = state.get("result", {})
        if "timings_ms" not in result:
            result["timings_ms"] = {}
        result["timings_ms"]["sql_execution_ms"] = round(exec_ms, 2)

        for k in ("sql_generation_tier", "sql_final_tier", "sql_repair_attempts", "sql_repair_success", "sql_cache_hit"):
            val = exec_meta.get(k)
            result[k] = val

        result["timings_ms"]["sql_repair_attempts"] = float(exec_meta.get("sql_repair_attempts", 0))
        result["timings_ms"]["sql_cache_hit"] = 1.0 if exec_meta.get("sql_cache_hit") else 0.0
        result["timings_ms"]["sql_repair_success"] = 1.0 if exec_meta.get("sql_repair_success") else 0.0

        return {
            "rows": rows, "final_sql": final_sql, "exec_error": exec_error,
            "error_type": error_type, "suggestions": suggestions, "result": result,
        }

    def route_after_execute(state: AgentState) -> str:
        if state.get("exec_error") is not None:
            # Fall back directly to Planner without restarting the whole pipeline!
            if not state.get("retried"):
                return "planner_fallback"
            return "report_exec_error"
        return "mask_and_analyze"

    async def report_exec_error_node(state: AgentState) -> dict:
        result = state["result"]
        exec_error = state.get("exec_error", "Execution error")
        suggestions = state.get("suggestions") or []
        result["attempted_sql"] = state.get("final_sql", "")
        result["error_type"] = state.get("error_type")
        result["error"] = exec_error
        result["suggestions"] = suggestions
        if suggestions:
            suggestion_str = " or ".join(f"'{s}'" for s in suggestions)
            reason_text = f"{exec_error}. Closest matching names available: {suggestion_str}."
        else:
            reason_text = exec_error
        result["report"] = await agent.report_service.generate_no_answer_response(
            question=state["question"],
            situation="The query failed to execute even after attempting to automatically repair it.",
            reason=reason_text,
            table_names=list(state["full_schema"].keys()),
        )
        return {"result": result}

    async def mask_and_analyze_node(state: AgentState) -> dict:
        import time
        result = state["result"]
        rows = state["rows"]
        result["sql"] = state["final_sql"]

        if settings.enable_data_masking and rows:
            try:
                rows, masked_cols = mask_sensitive_columns(rows, settings.extra_masked_column_patterns)
                if masked_cols:
                    logger.info("Masked sensitive columns in results: %s", masked_cols)
            except Exception as mask_err:
                logger.debug("Data masking skipped: %s", mask_err)

        result["results"] = rows

        analytics_result = None
        insight_result = None
        t0 = time.perf_counter()
        if rows:
            try:
                analytics_result = agent.analytics_engine.analyze(rows)
                insight_result = agent.insight_engine.generate_insights(analytics_result)
            except Exception as analytics_err:
                logger.warning("Analytics/Insight pipeline execution failed gracefully: %s", analytics_err)
        an_ms = (time.perf_counter() - t0) * 1000
        if "timings_ms" not in result:
            result["timings_ms"] = {}
        result["timings_ms"]["analytics_ms"] = round(an_ms, 2)

        return {"rows": rows, "result": result, "analytics_result": analytics_result, "insight_result": insight_result}

    def route_after_analyze(state: AgentState) -> str:
        return "no_rows_report" if not state["rows"] else "report"

    async def no_rows_report_node(state: AgentState) -> dict:
        result = state["result"]
        result["report"] = await agent.report_service.generate_no_answer_response(
            question=state["question"],
            situation="The query ran successfully but returned no matching rows.",
            reason="No records matched the filters implied by the question.",
            table_names=list(state["full_schema"].keys()),
        )
        result["success"] = True
        state["memory"].add_turn(state["question"], state["final_sql"], "No rows returned.", "database")
        return {"result": result}

    async def report_node(state: AgentState) -> dict:
        import time
        result = state["result"]
        rows = state["rows"]
        question = state["question"]
        final_sql = state["final_sql"]
        analysis_type = state["analysis_type"]

        truncated = len(rows) > MAX_ROWS_FOR_LLM
        rows_for_llm = rows[:MAX_ROWS_FOR_LLM] if truncated else rows

        t0 = time.perf_counter()
        report = await agent.report_service.generate_conversational_data_response(
            question=question,
            sql=final_sql,
            results=rows_for_llm,
            conversation_history=conversation_history,
            analytics_result=state.get("analytics_result"),
            insight_result=state.get("insight_result"),
        )
        chart = await agent.report_service.suggest_chart(
            question=question,
            sql=final_sql,
            results=rows_for_llm,
            analytics_result=state.get("analytics_result"),
            insight_result=state.get("insight_result"),
        )
        rep_ms = (time.perf_counter() - t0) * 1000

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

        if "timings_ms" not in result:
            result["timings_ms"] = {}
        result["timings_ms"]["report_generation_ms"] = round(rep_ms, 2)
        result["timings_ms"]["chart_suggestion_ms"] = 0.0

        state["memory"].add_turn(question, final_sql, build_result_summary(rows), "database")
        result["success"] = True
        return {"result": result}

    graph = StateGraph(AgentState)
    graph.add_node("understand", understand_node)
    graph.add_node("ground_schema", ground_schema_node)
    graph.add_node("generate_sql", generate_sql_node)
    graph.add_node("validate_sql", validate_sql_node)
    graph.add_node("cost_guard", cost_guard_node)
    graph.add_node("execute", execute_node)
    graph.add_node("planner_fallback", planner_fallback_node)
    graph.add_node("report_exec_error", report_exec_error_node)
    graph.add_node("mask_and_analyze", mask_and_analyze_node)
    graph.add_node("no_rows_report", no_rows_report_node)
    graph.add_node("report", report_node)

    graph.set_entry_point("understand")
    graph.add_conditional_edges("understand", route_after_understand, {END: END, "ground_schema": "ground_schema"})
    graph.add_edge("ground_schema", "generate_sql")
    graph.add_conditional_edges("generate_sql", route_after_generate, {END: END, "validate_sql": "validate_sql"})
    graph.add_conditional_edges("validate_sql", route_after_validate, {END: END, "cost_guard": "cost_guard"})
    graph.add_conditional_edges("cost_guard", route_after_cost_guard, {END: END, "execute": "execute"})
    graph.add_conditional_edges(
        "execute", route_after_execute,
        {"planner_fallback": "planner_fallback", "report_exec_error": "report_exec_error", "mask_and_analyze": "mask_and_analyze"},
    )
    graph.add_conditional_edges("planner_fallback", route_after_planner_fallback, {END: END, "report_exec_error": "report_exec_error"})
    graph.add_edge("report_exec_error", END)
    graph.add_conditional_edges("mask_and_analyze", route_after_analyze, {"no_rows_report": "no_rows_report", "report": "report"})
    graph.add_edge("no_rows_report", END)
    graph.add_edge("report", END)

    return graph.compile()


async def run_graph_ask(agent, question: str, db, memory, conversation_history: str) -> dict:
    """Entry point used by AnalystAgent.ask() when USE_LANGGRAPH_ORCHESTRATOR=true."""
    import time
    from app.utils.token_tracker import get_llm_trace, reset_llm_trace
    reset_llm_trace()

    req_start = time.perf_counter()
    compiled = agent.get_or_build_graph()
    initial_state: AgentState = {
        "question": question,
        "db": db,
        "memory": memory,
        "conversation_history": conversation_history,
        "result": _base_result(question),
    }
    final_state = await compiled.ainvoke(initial_state, config={"recursion_limit": 40})
    result = final_state.get("result", {})
    if "timings_ms" not in result:
        result["timings_ms"] = {}
    result["timings_ms"]["total_request_time_ms"] = round((time.perf_counter() - req_start) * 1000, 2)
    
    trace = get_llm_trace()
    result["llm_trace"] = trace
    result["llm_call_count"] = len(trace)
    return result
