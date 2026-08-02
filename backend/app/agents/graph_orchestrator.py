"""LangGraph Agentic Orchestrator (Rebuild Plan — Phase 2).

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
from app.core.config import settings
from app.security.cost_guard import check_query_cost
from app.security.data_masking import mask_sensitive_columns

MAX_FIX_ATTEMPTS = 2
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
        "intent": "database",
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
        question = state["question"]
        conversation_history = state["conversation_history"]
        if state.get("retried"):
            # One bounded extra hint so the reasoning layer (LLM path) or the
            # regex fallback gets a chance to reconsider - this is the
            # "reflect" half of the loop. Never repeated more than once.
            conversation_history = (
                f"{conversation_history}\n"
                f"[Previous attempt failed: {state.get('retry_hint', '')}. "
                f"Re-examine which tables/columns are actually relevant.]"
            )

        full_schema = agent.schema_service.get_schema()
        query_understanding = await agent.query_understander.understand(
            question, full_schema, conversation_history
        )
        logger.debug(
            "Query understanding source=%s analysis_type=%s confidence=%.2f",
            query_understanding.source, query_understanding.analysis_type, query_understanding.confidence,
        )

        catalog = None
        try:
            catalog = agent.catalog_builder.get_or_build()
            query_understanding = resolve_synonyms(question, catalog, query_understanding)
        except Exception as catalog_err:
            logger.debug("Schema catalog lookup skipped: %s", catalog_err)

        return {
            "full_schema": full_schema,
            "query_understanding": query_understanding,
            "catalog": catalog,
            "analysis_type": query_understanding.analysis_type,
        }

    async def ground_schema_node(state: AgentState) -> dict:
        query_understanding = state["query_understanding"]
        grounded_schema = agent.schema_grounding_engine.build_grounded_schema(
            schema=state["full_schema"],
            query_understanding=query_understanding,
            question=state["question"],
            analysis_type=query_understanding.analysis_type,
            catalog=state.get("catalog"),
        )
        return {"grounded_schema": grounded_schema, "schema_text": grounded_schema.schema_text}

    def route_after_ground(state: AgentState) -> str:
        query_understanding = state["query_understanding"]
        analysis_type = query_understanding.analysis_type
        if analysis_type in COMPLEX_ANALYSIS_TYPES or query_understanding.requires_multi_step:
            return "planner"
        return "generate_sql"

    async def planner_node(state: AgentState) -> dict:
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
            if plan_result:
                return {"result": plan_result, "plan_completed": True}
        # Plan wasn't actually multi-step after all - fall through to the
        # normal single-step path exactly like the linear pipeline does.
        return {"plan_completed": False}

    def route_after_planner(state: AgentState) -> str:
        return END if state.get("plan_completed") else "generate_sql"

    async def generate_sql_node(state: AgentState) -> dict:
        question = state["question"]
        schema_text = state["schema_text"]
        analysis_type = state["analysis_type"]
        use_voting = should_use_self_consistency(question, analysis_type)
        use_fast = choose_sql_generation_tier(question, analysis_type, state["query_understanding"].confidence)
        sql = await agent.sql_generator.generate_sql(
            question, schema_text, state["db"], state["conversation_history"],
            use_self_consistency=use_voting, use_fast_model=(use_fast == "fast"),
        )
        result = _base_result(question)
        result["sql"] = sql
        result["analysis_type"] = analysis_type.value if hasattr(analysis_type, "value") else str(analysis_type)

        reason = agent.sql_generator.unanswerable_reason(sql)
        if reason:
            logger.info("Question flagged UNANSWERABLE: %s", reason)
            result["report"] = await agent.report_service.generate_no_answer_response(
                question=question,
                situation="This question cannot be answered using the current database schema.",
                reason=reason,
                table_names=list(state["full_schema"].keys()),
            )
            result["success"] = True
            state["memory"].add_turn(question, sql, f"Unanswerable: {reason}", "database")
            return {"sql": sql, "result": result}

        return {"sql": sql, "result": result}

    def route_after_generate(state: AgentState) -> str:
        return END if state["result"].get("report") else "validate_sql"

    async def validate_sql_node(state: AgentState) -> dict:
        sql = state["sql"]
        result = state["result"]
        validation = validate_sql(sql)
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
        rows, final_sql, exec_error, error_type, suggestions = await agent.sql_generator.execute_with_repair(
            question=state["question"], schema_text=state["schema_text"], sql=state["sql"],
            db=state["db"], max_fix_attempts=MAX_FIX_ATTEMPTS,
        )
        return {
            "rows": rows, "final_sql": final_sql, "exec_error": exec_error,
            "error_type": error_type, "suggestions": suggestions,
        }

    def route_after_execute(state: AgentState) -> str:
        if state.get("exec_error") is not None:
            # Reflect-and-retry: only once, and only if we haven't already.
            if not state.get("retried"):
                return "reflect_retry"
            return "report_exec_error"
        return "mask_and_analyze"

    async def reflect_retry_node(state: AgentState) -> dict:
        logger.info("Execution failed, retrying once with a reflection hint: %s", state.get("exec_error"))
        return {"retried": True, "retry_hint": state.get("exec_error", "")}

    async def report_exec_error_node(state: AgentState) -> dict:
        result = state["result"]
        exec_error = state["exec_error"]
        suggestions = state.get("suggestions") or []
        result["attempted_sql"] = state["final_sql"]
        result["error_type"] = state["error_type"]
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
        if rows:
            try:
                analytics_result = agent.analytics_engine.analyze(rows)
                insight_result = agent.insight_engine.generate_insights(analytics_result)
            except Exception as analytics_err:
                logger.warning("Analytics/Insight pipeline execution failed gracefully: %s", analytics_err)

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
        result = state["result"]
        rows = state["rows"]
        question = state["question"]
        final_sql = state["final_sql"]
        analysis_type = state["analysis_type"]

        truncated = len(rows) > MAX_ROWS_FOR_LLM
        rows_for_llm = rows[:MAX_ROWS_FOR_LLM] if truncated else rows

        report = await agent.report_service.generate_report(
            question, final_sql, rows_for_llm,
            analytics_result=state.get("analytics_result"),
            insight_result=state.get("insight_result"),
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

        chart = await agent.report_service.suggest_chart(
            question, final_sql, rows_for_llm,
            analytics_result=state.get("analytics_result"),
            insight_result=state.get("insight_result"),
        )
        result["chart_suggestion"] = chart

        state["memory"].add_turn(question, final_sql, build_result_summary(rows), "database")
        result["success"] = True
        return {"result": result}

    graph = StateGraph(AgentState)
    graph.add_node("understand", understand_node)
    graph.add_node("ground_schema", ground_schema_node)
    graph.add_node("planner", planner_node)
    graph.add_node("generate_sql", generate_sql_node)
    graph.add_node("validate_sql", validate_sql_node)
    graph.add_node("cost_guard", cost_guard_node)
    graph.add_node("execute", execute_node)
    graph.add_node("reflect_retry", reflect_retry_node)
    graph.add_node("report_exec_error", report_exec_error_node)
    graph.add_node("mask_and_analyze", mask_and_analyze_node)
    graph.add_node("no_rows_report", no_rows_report_node)
    graph.add_node("report", report_node)

    graph.set_entry_point("understand")
    graph.add_edge("understand", "ground_schema")
    graph.add_conditional_edges("ground_schema", route_after_ground, {"planner": "planner", "generate_sql": "generate_sql"})
    graph.add_conditional_edges("planner", route_after_planner, {END: END, "generate_sql": "generate_sql"})
    graph.add_conditional_edges("generate_sql", route_after_generate, {END: END, "validate_sql": "validate_sql"})
    graph.add_conditional_edges("validate_sql", route_after_validate, {END: END, "cost_guard": "cost_guard"})
    graph.add_conditional_edges("cost_guard", route_after_cost_guard, {END: END, "execute": "execute"})
    graph.add_conditional_edges(
        "execute", route_after_execute,
        {"reflect_retry": "reflect_retry", "report_exec_error": "report_exec_error", "mask_and_analyze": "mask_and_analyze"},
    )
    graph.add_edge("reflect_retry", "understand")
    graph.add_edge("report_exec_error", END)
    graph.add_conditional_edges("mask_and_analyze", route_after_analyze, {"no_rows_report": "no_rows_report", "report": "report"})
    graph.add_edge("no_rows_report", END)
    graph.add_edge("report", END)

    return graph.compile()


async def run_graph_ask(agent, question: str, db, memory, conversation_history: str) -> dict:
    """Entry point used by AnalystAgent.ask() when USE_LANGGRAPH_ORCHESTRATOR=true."""
    compiled = agent.get_or_build_graph()
    initial_state: AgentState = {
        "question": question,
        "db": db,
        "memory": memory,
        "conversation_history": conversation_history,
        "result": _base_result(question),
    }
    # Recursion limit accounts for the single bounded reflect-retry loop
    # (understand -> ... -> execute -> reflect_retry -> understand -> ...)
    # plus normal step count; generous but still finite/safe.
    final_state = await compiled.ainvoke(initial_state, config={"recursion_limit": 40})
    return final_state["result"]
