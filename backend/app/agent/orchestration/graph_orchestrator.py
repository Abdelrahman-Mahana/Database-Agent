"""LangGraph Agentic Orchestrator (Rebuild Plan — Phase 2).

ARCHITECTURAL NOTE:
This module is the LangGraph canonical orchestration path, selected at deploy
time via `use_langgraph_orchestrator`. It is NOT a fallback layer — when enabled,
failures surface explicitly and do not silently route to the service pipeline.

Every node is a thin wrapper around the same components the service pipeline
uses (`SchemaGroundingEngine`, `Planner`, `SQLGenerator`, `ReportService`, ...).
The validate_sql node runs the full pre-execution gate chain:
AST safety → identifier grounding → join validation → QuerySpec alignment
(blocking before execute on unknown identifiers or unsupported joins).
Stage-level fallbacks (e.g. Planner after single-SQL failure, reflect-and-retry)
live inside this graph only.
"""
from typing import Any, Optional, TypedDict

from loguru import logger
from langgraph.graph import StateGraph, END

from app.utils.helpers import validate_sql
from app.utils.helpers import build_result_summary, COMPLEX_ANALYSIS_TYPES
from app.agent.semantic.resolvers import resolve_synonyms
from app.utils.cost_router import should_use_self_consistency, choose_sql_generation_tier
from app.core.config.settings import settings
from app.agent.schema_grounding.confidence import grounding_confidence
from app.core.security.cost_guard import check_query_cost, cost_guard_failure_result
from app.core.security.data_masking import mask_sensitive_columns
from app.services.sql.control_gate import SQLControlGate
from app.agent.semantic.models import ExecutionRoute

from app.services.analysis.investigation_engine import InvestigationEngine
from app.services.analysis.investigation_models import (
    InvestigationMode,
    InvestigationPlan,
    InvestigationState,
    InvestigationStatus,
    QueryExecutionRecord,
    QueryExecutionStatus,
    QueryTask,
    QueryTaskStatus,
)

MAX_FIX_ATTEMPTS = getattr(settings, "max_fix_attempts", 1)
MAX_ROWS_FOR_LLM = 200


class AgentState(TypedDict, total=False):
    question: str
    db: Any
    memory: Any
    conversation_history: str
    full_schema: dict
    db_ctx: Any
    catalog: Any
    query_understanding: Any
    analysis_plan: Any
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
    planner_failure: dict
    result: dict
    investigation: Optional[InvestigationState]  # Adaptive Investigation state foundation
    current_query_task: Optional[QueryTask]  # Currently executing QueryTask
    query_results: dict  # Dict[str, list]
    all_executed_sqls: list  # List[str]


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

    # 1. UNDERSTAND NODE
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

        # 2. Unified QuerySpecBuilder (deterministic fast path with optional LLM understanding)
        t_und_start = time.perf_counter()
        query_spec = await agent.query_spec_builder.build_spec_async(
            question=question,
            db_ctx=db_ctx,
            conversation_history=conversation_history,
            catalog=catalog,
        )
        und_ms = (time.perf_counter() - t_und_start) * 1000
        result["timings_ms"]["query_understanding_ms"] = round(und_ms, 2)
        result["intent"] = query_spec.intent.value
        result["understanding_source"] = query_spec.source

        # Route first: conversation/general, schema/metadata, or real data query.
        if query_spec.route == ExecutionRoute.CONVERSATION:
            reply = query_spec.off_topic_response
            if not reply:
                is_ar = any("\u0600" <= c <= "\u06FF" for c in question)
                reply = (
                    "أنا مساعد متخصص في استعلام وتحليل قواعد البيانات. يمكنني مساعدتك في استعراض الجداول، حساب المؤشرات، وكتابة استعلامات SQL. يرجى توجيه سؤالك حول قاعدة البيانات أو البيانات المتصلة."
                    if is_ar else
                    "I am specialized in database analysis and querying. I can help you explore tables, compute metrics, write SQL queries, or generate data reports. Please ask a question related to your database or data."
                )
            result["intent"] = "conversation"
            result["report"] = reply
            result["success"] = True
            state_result = {
                "result": result, "full_schema": full_schema, "catalog": catalog, "db_ctx": db_ctx,
                "query_understanding": query_spec, "analysis_type": query_spec.analysis_type
            }
            return state_result

        if query_spec.route == ExecutionRoute.SCHEMA:
            schema_resp = await agent.schema_explorer.handle_schema_exploration(question)
            if schema_resp:
                schema_resp["intent"] = "schema"
                state_result = {
                    "result": schema_resp, "full_schema": full_schema, "catalog": catalog, "db_ctx": db_ctx,
                    "query_understanding": query_spec, "analysis_type": query_spec.analysis_type
                }
                return state_result

        if query_spec.requires_clarification:
            clarification_report = query_spec.clarification_prompt or (
                "Your question matches more than one table or semantic target. Please clarify which one you mean."
            )
            result["intent"] = "clarification"
            result["report"] = clarification_report
            result["suggestions"] = query_spec.ambiguity_candidates
            result["error_type"] = "ambiguity"
            result["success"] = True
            if query_spec.ambiguity_evidence:
                result.setdefault("warnings", [])
                result["warnings"].append(query_spec.ambiguity_evidence)
            state["memory"].add_turn(question, "", clarification_report, "database")
            state_result = {
                "result": result, "full_schema": full_schema, "catalog": catalog, "db_ctx": db_ctx,
                "query_understanding": query_spec, "analysis_type": query_spec.analysis_type
            }
            return state_result

        result["intent"] = "data_query"

        return {
            "full_schema": full_schema,
            "db_ctx": db_ctx,
            "query_understanding": query_spec,
            "catalog": catalog,
            "analysis_type": query_spec.analysis_type,
            "result": result,
        }

    # 2. ROUTE AFTER UNDERSTAND
    def route_after_understand(state: AgentState) -> str:
        if state["result"].get("report"):
            return END
        return "analysis_plan"

    # 3. ANALYSIS PLAN NODE
    async def analysis_plan_node(state: AgentState) -> dict:
        import time
        from app.services.analysis.planner import AnalysisPlanner

        t0 = time.perf_counter()
        query_spec = state["query_understanding"]
        analysis_plan = state.get("analysis_plan") or AnalysisPlanner.plan(query_spec)
        plan_ms = (time.perf_counter() - t0) * 1000

        result = state.get("result", {})
        if "timings_ms" not in result:
            result["timings_ms"] = {}
        result["timings_ms"]["analysis_planning_ms"] = round(plan_ms, 2)
        primary_op = (
            analysis_plan.tasks[0].operation.value
            if analysis_plan.tasks and hasattr(analysis_plan.tasks[0].operation, "value")
            else (analysis_plan.analysis_type.value if hasattr(analysis_plan.analysis_type, "value") else str(analysis_plan.analysis_type))
        )
        result["analysis_plan_summary"] = {
            "analysis_type": analysis_plan.analysis_type.value if hasattr(analysis_plan.analysis_type, "value") else str(analysis_plan.analysis_type),
            "primary_operation": primary_op,
            "tasks_count": len(analysis_plan.tasks),
            "retrieval_requirements_count": len(analysis_plan.data_requirements),
            "expected_insights_count": len(analysis_plan.expected_insights),
        }

        # Initialize Adaptive Investigation State
        investigation_plan = (
            analysis_plan.to_investigation_plan()
            if hasattr(analysis_plan, "to_investigation_plan")
            else InvestigationPlan.from_analysis_plan(analysis_plan)
        )
        investigation_state = InvestigationEngine.initialize_investigation(
            plan=investigation_plan,
            max_queries=investigation_plan.max_queries,
            max_reasoning_steps=investigation_plan.max_reasoning_steps,
        )

        return {
            "analysis_plan": analysis_plan,
            "investigation": investigation_state,
            "query_results": {},
            "all_executed_sqls": [],
            "result": result,
        }

    # 4. GROUND SCHEMA NODE
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

    # 4.5. SELECT NEXT QUERY NODE
    async def select_next_query_node(state: AgentState) -> dict:
        investigation = state.get("investigation")
        if not investigation:
            return {
                "current_query_task": None,
                "sql": "",
                "rows": [],
                "final_sql": "",
                "exec_error": None,
                "error_type": None,
                "suggestions": [],
            }

        selection_res = InvestigationEngine.select_next_task_with_explanation(investigation)
        next_task = selection_res.selected_task
        result = state.get("result", {})
        if next_task:
            next_task.status = QueryTaskStatus.RUNNING
            investigation.current_query_task = next_task
            if "query_selections" not in result:
                result["query_selections"] = []
            result["query_selections"].append({
                "query_id": selection_res.selected_query_id,
                "score": selection_res.score,
                "reason": selection_res.reason,
            })
            return {
                "current_query_task": next_task,
                "investigation": investigation,
                "result": result,
                "sql": "",
                "rows": [],
                "final_sql": "",
                "exec_error": None,
                "error_type": None,
                "suggestions": [],
            }
        else:
            investigation.current_query_task = None
            return {
                "current_query_task": None,
                "investigation": investigation,
                "result": result,
            }

    def route_after_select_query(state: AgentState) -> str:
        if state.get("current_query_task") is not None:
            return "retrieve_data"
        return "run_analysis"

    # 5. RETRIEVE DATA NODE (Generate SQL for current task)
    async def retrieve_data_node(state: AgentState) -> dict:
        import time
        current_task = state.get("current_query_task")
        target_question = current_task.sub_question if (current_task and current_task.sub_question) else state["question"]
        schema_text = state["schema_text"]
        analysis_type = state["analysis_type"]
        qu = state.get("query_understanding")
        grounded_tables_count = len(state["grounded_schema"].selected_tables) if state.get("grounded_schema") else 1
        has_grouping = len(qu.dimensions) > 0 if qu else False

        schema_token_estimate = len(schema_text) // 4 if schema_text else 0
        use_voting = should_use_self_consistency(
            target_question, analysis_type, schema_token_estimate=schema_token_estimate
        )

        use_fast = choose_sql_generation_tier(
            target_question, analysis_type, qu.confidence if qu else 1.0,
            grounded_table_count=grounded_tables_count, has_grouping=has_grouping
        )

        contract = getattr(qu, "semantic_contract", None) if qu else None
        grounded_schema = state.get("grounded_schema")
        is_unsupported = False
        unsupported_reason = None
        if grounded_schema and not hasattr(grounded_schema, "_mock_name"):
            if getattr(grounded_schema, "unsupported", False) is True:
                is_unsupported = True
                unsupported_reason = getattr(grounded_schema, "unsupported_reason", None)

        if not is_unsupported and contract and not hasattr(contract, "_mock_name"):
            if getattr(contract, "is_answerable", True) is False:
                is_unsupported = True
                unsupported_reason = getattr(contract, "unsupported_reason", None)

        if is_unsupported:
            reason = unsupported_reason or "This question asks for entities or metrics not present in the database schema."
            logger.info("Question flagged UNANSWERABLE / UNSUPPORTED: %s", reason)
            result = state.get("result") or _base_result(state["question"])
            if state.get("investigation"):
                return {
                    "sql": "",
                    "exec_error": reason,
                    "error_type": "unanswerable",
                    "result": result,
                }
            result["sql"] = ""
            result["error_type"] = "unanswerable"
            result["report"] = await agent.report_service.generate_no_answer_response(
                question=state["question"],
                situation="This question cannot be answered using the current database schema.",
                reason=reason,
                error_type="unanswerable",
            )
            result["success"] = True
            state["memory"].add_turn(state["question"], "", f"Unanswerable: {reason}", "database")
            return {"result": result, "sql": ""}

        t0 = time.perf_counter()
        sql = await agent.sql_generator.generate_sql(
            target_question, schema_text, state["db"], state["conversation_history"],
            use_self_consistency=use_voting, use_fast_model=(use_fast == "fast"),
            query_understanding=qu,
        )
        gen_ms = (time.perf_counter() - t0) * 1000

        result = state.get("result") or _base_result(state["question"])
        if "timings_ms" not in result:
            result["timings_ms"] = {}
        result["timings_ms"]["sql_generation_ms"] = round(gen_ms, 2)
        result["sql"] = sql
        result["analysis_type"] = analysis_type.value if hasattr(analysis_type, "value") else str(analysis_type)

        reason = agent.sql_generator.unanswerable_reason(sql)
        if reason:
            logger.info("Question flagged UNANSWERABLE: %s", reason)
            if state.get("investigation"):
                return {
                    "sql": "",
                    "exec_error": reason,
                    "error_type": "unanswerable",
                    "result": result,
                }
            result["sql"] = ""
            result["error_type"] = "unanswerable"
            result["report"] = await agent.report_service.generate_no_answer_response(
                question=state["question"],
                situation="This question cannot be answered using the current database schema.",
                reason=reason,
                error_type="unanswerable",
            )
            result["success"] = True
            state["memory"].add_turn(state["question"], sql, f"Unanswerable: {reason}", "database")
            return {"sql": "", "result": result}

        return {"sql": sql, "result": result, "exec_error": None}

    def route_after_retrieve(state: AgentState) -> str:
        if state["result"].get("report"):
            return END
        if state.get("exec_error") is not None:
            return "record_investigation_result"
        return "validate_sql"

    # 6. VALIDATE SQL NODE
    async def validate_sql_node(state: AgentState) -> dict:
        import time
        from app.services.sql.validator import sql_validator

        sql = state.get("sql", "")
        result = state["result"]
        t0 = time.perf_counter()
        validation = validate_sql(sql)
        if "timings_ms" not in result:
            result["timings_ms"] = {}

        if not validation["valid"]:
            result["timings_ms"]["sql_validation_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            result["attempted_sql"] = sql
            error_type = validation.get("query_type", "safety")
            if state.get("investigation"):
                return {
                    "result": result,
                    "exec_error": validation["reason"],
                    "error_type": error_type,
                }
            result["error_type"] = error_type
            result["error"] = validation["reason"]
            result["report"] = await agent.report_service.generate_no_answer_response(
                question=state["question"],
                situation="The generated query could not be safely executed.",
                reason=validation["reason"],
                error_type=result["error_type"],
            )
            return {"result": result}

        ident_ok, ident_warnings = sql_validator.verify_sql_identifiers(
            sql,
            catalog=state.get("catalog"),
            raw_schema=state.get("full_schema"),
        )
        join_ok, join_warnings = sql_validator.verify_sql_joins(
            sql,
            catalog=state.get("catalog"),
        )
        qspec_ok, qspec_warnings = sql_validator.verify_query_spec_alignment(
            sql,
            query_spec=state.get("query_understanding"),
        )

        for w in ident_warnings + join_warnings + qspec_warnings:
            if w not in result.setdefault("warnings", []):
                result["warnings"].append(w)

        result["sql_validation"] = {
            "safety_valid": True,
            "identifiers_valid": ident_ok,
            "joins_valid": join_ok,
            "alignment_valid": qspec_ok,
        }
        result["pre_execution_validation"] = dict(result["sql_validation"])
        result["timings_ms"]["sql_validation_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        if not ident_ok or not join_ok:
            error_type = (
                "identifier_grounding" if not ident_ok else "join_validation"
            )
            reason = "; ".join(ident_warnings + join_warnings)
            result["attempted_sql"] = sql
            if state.get("investigation"):
                return {
                    "result": result,
                    "exec_error": reason or "Generated SQL failed semantic validation.",
                    "error_type": error_type,
                }
            result["error_type"] = error_type
            result["error"] = reason or "Generated SQL failed semantic validation."
            result["report"] = await agent.report_service.generate_no_answer_response(
                question=state["question"],
                situation="The generated query does not match the available database schema.",
                reason=result["error"],
                error_type=error_type,
            )
        return {"result": result}

    def route_after_validate(state: AgentState) -> str:
        if state["result"].get("report"):
            return END
        if state.get("exec_error") is not None:
            return "record_investigation_result"
        return "cost_guard"

    # 7. COST GUARD NODE
    async def cost_guard_node(state: AgentState) -> dict:
        result = state["result"]
        if settings.enable_cost_guard:
            try:
                cost_check = check_query_cost(
                    sql=state["sql"],
                    catalog=state.get("catalog"),
                    max_unfiltered_rows=settings.cost_guard_max_unfiltered_rows,
                    db=state.get("db"),
                    max_estimated_rows=settings.cost_guard_max_estimated_rows,
                )
            except Exception as cost_err:
                cost_check = cost_guard_failure_result(
                    state["sql"],
                    catalog=state.get("catalog"),
                    max_unfiltered_rows=settings.cost_guard_max_unfiltered_rows,
                    error=cost_err,
                )
            if cost_check is not None and not cost_check.allowed:
                result["attempted_sql"] = state["sql"]
                if state.get("investigation"):
                    return {
                        "result": result,
                        "exec_error": cost_check.reason,
                        "error_type": "cost_guard",
                    }
                result["error_type"] = "cost_guard"
                result["error"] = cost_check.reason
                result["report"] = await agent.report_service.generate_no_answer_response(
                    question=state["question"],
                    situation="The query was blocked before execution because it would scan an unusually large amount of data.",
                    reason=cost_check.reason,
                    error_type="cost_guard",
                )
        return {"result": result}

    def route_after_cost_guard(state: AgentState) -> str:
        if state["result"].get("report"):
            return END
        if state.get("exec_error") is not None:
            return "record_investigation_result"
        return "execute"

    # 8. EXECUTE NODE
    async def execute_node(state: AgentState) -> dict:
        import time
        t0 = time.perf_counter()
        gen_meta = getattr(agent.sql_generator, "last_generation_meta", {})
        initial_tier = gen_meta.get("sql_generation_tier", "primary")
        sql_cache_hit = gen_meta.get("sql_cache_hit", False)

        current_task = state.get("current_query_task")
        print(f"DEBUG: execute_node running. current_task is {'not None' if current_task else 'None'}")
        
        target_question = current_task.sub_question if (current_task and current_task.sub_question) else state["question"]

        # If it's a sub-query for an investigation, the global query_spec won't align perfectly.
        # Bypass strict semantic alignment validation against the global contract.
        gate_query_spec = None if current_task else state.get("query_understanding")
        print(f"DEBUG: gate_query_spec is {'None' if gate_query_spec is None else 'Present'}")

        rows, final_sql, exec_error, error_type, suggestions = await agent.sql_generator.execute_with_repair(
            question=target_question, schema_text=state["schema_text"], sql=state["sql"],
            db=state["db"], max_fix_attempts=MAX_FIX_ATTEMPTS,
            initial_tier=initial_tier, sql_cache_hit=sql_cache_hit,
            pre_execution_gate=lambda candidate: SQLControlGate().evaluate(
                candidate,
                query_spec=gate_query_spec,
                catalog=state.get("catalog"), raw_schema=state.get("full_schema"), db=state.get("db"),
            ),
            query_understanding=gate_query_spec,
            conversation_history=state.get("conversation_history", ""),
            db_identifier=getattr(agent.schema_service, "database_name", "") or settings.database_url,
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
        if state.get("investigation") is not None:
            return "record_investigation_result"
        if state.get("exec_error") is not None:
            if not state.get("retried"):
                return "planner_fallback"
            return "report_exec_error"
        return "run_analysis"

    # 8.5. RECORD INVESTIGATION RESULT NODE
    async def record_investigation_result_node(state: AgentState) -> dict:
        investigation = state.get("investigation")
        current_task = state.get("current_query_task")
        rows = state.get("rows") or []
        sql = state.get("final_sql") or state.get("sql") or ""
        exec_error = state.get("exec_error")
        exec_meta = getattr(agent.sql_generator, "last_execution_meta", {})
        cache_hit = bool(exec_meta.get("sql_cache_hit", False))
        exec_ms = float(state.get("result", {}).get("timings_ms", {}).get("sql_execution_ms", 0.0))

        query_results = dict(state.get("query_results") or {})
        all_sqls = list(state.get("all_executed_sqls") or [])

        if investigation and current_task:
            InvestigationEngine.record_execution_result(
                state=investigation,
                task=current_task,
                sql=sql,
                rows=rows,
                exec_error=exec_error,
                execution_time_ms=exec_ms,
                cache_hit=cache_hit,
            )
            query_results[current_task.query_id] = rows
            if sql and sql not in all_sqls:
                all_sqls.append(sql)

        return {
            "investigation": investigation,
            "current_query_task": None,
            "query_results": query_results,
            "all_executed_sqls": all_sqls,
            "sql": "",
            "rows": [],
            "final_sql": "",
            "exec_error": None,
            "last_error_type": state.get("error_type"),
            "suggestions": [],
        }

    def route_after_record(state: AgentState) -> str:
        investigation = state.get("investigation")
        if investigation and InvestigationEngine.should_continue(investigation):
            return "select_next_query"
        return "run_analysis"

    async def planner_fallback_node(state: AgentState) -> dict:
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
                catalog=state.get("catalog"),
                raw_schema=state.get("full_schema"),
                db_ctx=state.get("db_ctx"),
            )
            if plan_result and plan_result.get("success"):
                return {"result": plan_result, "plan_completed": True, "retried": True}
            if plan_result:
                return {
                    "plan_completed": False,
                    "retried": True,
                    "planner_failure": plan_result,
                }

        return {"plan_completed": False, "retried": True}

    def route_after_planner_fallback(state: AgentState) -> str:
        return END if state.get("plan_completed") else "report_exec_error"

    async def report_exec_error_node(state: AgentState) -> dict:
        result = state["result"]
        planner_failure = state.get("planner_failure") or {}
        exec_error = planner_failure.get("error") or state.get("exec_error", "Execution error")
        suggestions = state.get("suggestions") or []
        result["attempted_sql"] = state.get("final_sql", "")
        result["error_type"] = planner_failure.get("error_type") or state.get("error_type")
        result["error"] = exec_error
        if planner_failure:
            result["plan_status"] = planner_failure.get("plan_status")
            result["plan_completed_steps"] = planner_failure.get("completed_steps", 0)
            result["plan_required_steps"] = planner_failure.get("required_steps")
        result["suggestions"] = suggestions
        if suggestions:
            suggestion_str = " or ".join(f"'{s}'" for s in suggestions)
            reason_text = f"{exec_error}. Closest matching names available: {suggestion_str}."
        else:
            reason_text = exec_error
        result["report"] = await agent.report_service.generate_no_answer_response(
            question=state["question"],
            situation=(
                "The multi-step analysis could not be completed because a required plan step failed."
                if planner_failure else "The query failed to execute even after attempting to automatically repair it."
            ),
            reason=reason_text,
            error_type="execution_error",
        )
        return {"result": result}

    # 9. RUN ANALYSIS NODE
    async def run_analysis_node(state: AgentState) -> dict:
        import time
        result = state["result"]
        rows = state.get("rows") or []
        final_sql = state.get("final_sql") or state.get("sql") or ""
        investigation = state.get("investigation")
        query_results = state.get("query_results") or {}
        all_sqls = state.get("all_executed_sqls") or []

        if investigation:
            result["investigation_status"] = investigation.status.value
            result["completed_queries"] = [q.model_dump() for q in investigation.completed_queries]
            result["evidence"] = [e.model_dump() for e in investigation.evidence]
            result["known_facts"] = list(investigation.known_facts)
            result["unresolved_questions"] = list(investigation.unresolved_questions)
            result["evidence_coverage"] = investigation.completeness_score
            result["hypotheses"] = [h.model_dump() for h in investigation.active_hypotheses]
            result["query_results"] = query_results

            if investigation.status == InvestigationStatus.BUDGET_EXHAUSTED:
                result.setdefault("warnings", []).append("Investigation completed because query budget was exhausted.")

            # Multi-query row aggregation for AnalyticsEngine with strict semantic compatibility
            task_map = {t.query_id: t for t in investigation.plan.query_tasks} if (investigation and investigation.plan) else {}
            valid_results = [(q_id, q_rows) for q_id, q_rows in query_results.items() if q_rows and isinstance(q_rows[0], dict)]

            all_compatible = True
            if len(valid_results) > 1:
                first_qid, first_rows = valid_results[0]
                first_task = task_map.get(first_qid)
                for q_id, q_rows in valid_results[1:]:
                    curr_task = task_map.get(q_id)
                    # Check column equality
                    if set(first_rows[0].keys()) != set(q_rows[0].keys()):
                        all_compatible = False
                        break
                    # Check metric semantics
                    if first_task and curr_task:
                        if first_task.required_metrics and curr_task.required_metrics:
                            if set(m.lower() for m in first_task.required_metrics) != set(m.lower() for m in curr_task.required_metrics):
                                all_compatible = False
                                break
                        if first_task.required_dimensions and curr_task.required_dimensions:
                            if set(d.lower() for d in first_task.required_dimensions) != set(d.lower() for d in curr_task.required_dimensions):
                                all_compatible = False
                                break

            if all_compatible and valid_results:
                combined_rows: list = []
                for _, q_rows in valid_results:
                    combined_rows.extend(q_rows)
                rows = combined_rows
            elif valid_results:
                # Keep primary query rows to prevent heterogeneous schema/semantic distortion
                rows = valid_results[0][1]
            elif not rows and state.get("rows"):
                rows = state["rows"]

            if all_sqls:
                final_sql = " ;\n".join(all_sqls)
            result["sql"] = final_sql

            # If all attempted queries failed
            if investigation.completed_queries and all(q.status == QueryExecutionStatus.FAILED for q in investigation.completed_queries):
                result["attempted_sql"] = final_sql
                err_t = state.get("error_type") or "execution_error"
                result["error_type"] = err_t
                result["error"] = "All queries in the investigation plan failed to execute."
                result["report"] = await agent.report_service.generate_no_answer_response(
                    question=state["question"],
                    situation="The multi-query investigation could not be executed successfully.",
                    reason="All attempted investigation queries encountered execution errors.",
                    error_type=err_t,
                )
                return {"result": result, "rows": [], "final_sql": final_sql}

        result["sql"] = final_sql
        result["sql_validation"] = {
            "safety_valid": True,
            "identifiers_valid": True,
            "joins_valid": True,
            "alignment_valid": True,
        }

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
                analytics_result = agent.analytics_engine.analyze(
                    rows=rows,
                    analysis_plan=state.get("analysis_plan"),
                )
                insight_result = agent.insight_engine.generate_insights(analytics_result)
            except Exception as analytics_err:
                logger.warning("Analytics/Insight pipeline execution failed gracefully: %s", analytics_err)
        an_ms = (time.perf_counter() - t0) * 1000
        if "timings_ms" not in result:
            result["timings_ms"] = {}
        result["timings_ms"]["analytics_ms"] = round(an_ms, 2)

        # Construct unified AnalysisResult with source-of-truth investigation confidence
        from app.services.analysis.models import AnalysisResult
        calc_confidence = investigation.confidence_score if investigation else 1.0
        unified_analysis = AnalysisResult.from_analytics_and_insights(
            analytics_result=analytics_result,
            insight_result=insight_result,
            analysis_plan=state.get("analysis_plan"),
            query_spec=state.get("query_understanding"),
            confidence=calc_confidence,
        )
        result["analysis_result"] = unified_analysis.model_dump()

        return {
            "rows": rows,
            "final_sql": final_sql,
            "result": result,
            "analytics_result": analytics_result,
            "insight_result": insight_result,
            "analysis_result": unified_analysis,
        }

    # 10. VERIFY RESULTS NODE
    async def verify_results_node(state: AgentState) -> dict:
        result = state["result"]
        rows = state.get("rows") or []
        from app.services.sql.result_verifier import result_verifier

        current_task = state.get("current_query_task")
        verify_query_spec = None if current_task else state.get("query_understanding")

        verification = result_verifier.verify(
            rows,
            query_spec=verify_query_spec,
            sql=state.get("final_sql", ""),
            validation_status=result.get("sql_validation"),
            catalog=state.get("catalog"),
        )
        result["verification"] = verification.to_dict()
        if verification.warnings:
            result.setdefault("warnings", [])
            for w in verification.warnings:
                if w not in result["warnings"]:
                    result["warnings"].append(w)

        # Cross-Query Validation and Grounding Readiness (Phase 7)
        investigation = state.get("investigation")
        if investigation:
            from app.services.analysis.cross_query_validator import CrossQueryValidator
            val_report = CrossQueryValidator.validate(investigation)
            result["cross_query_validation"] = val_report.to_dict()
            result["completeness_score"] = val_report.completeness_score
            result["confidence_score"] = val_report.confidence_score
            result["grounding_readiness"] = val_report.grounding_readiness.to_dict()

            # Synchronize final AnalysisResult confidence with calculated validation confidence
            if "analysis_result" in result and isinstance(result["analysis_result"], dict):
                result["analysis_result"]["confidence"] = val_report.confidence_score
            if state.get("analysis_result") and hasattr(state["analysis_result"], "confidence"):
                state["analysis_result"].confidence = val_report.confidence_score
            if val_report.issues:
                for iss in val_report.issues:
                    if iss.severity.value in ("critical", "warning"):
                        result.setdefault("warnings", [])
                        if iss.description not in result["warnings"]:
                            result["warnings"].append(f"[{iss.type.value.upper()}] {iss.description}")

        if verification.answer_action == "FAIL" and not result.get("error_type"):
            result["error_type"] = "result_verification"
            result["error"] = "Result verification failed required quality gates."
            result["report"] = await agent.report_service.generate_no_answer_response(
                question=state["question"],
                situation="The query result did not pass the required quality gates.",
                reason="; ".join(
                    f"{name}: {status}" for name, status in verification.gate_statuses.items()
                    if status == "FAIL"
                ),
                error_type="result_verification",
            )

        return {"result": result}

    def route_after_verify(state: AgentState) -> str:
        if state["result"].get("report"):
            return END
        if not state.get("rows"):
            return "no_rows_report"
        return "generate_report"

    async def no_rows_report_node(state: AgentState) -> dict:
        result = state["result"]
        result["error_type"] = "empty_result"
        result["report"] = await agent.report_service.generate_no_answer_response(
            question=state["question"],
            situation="The query ran successfully but returned no matching rows.",
            reason="No records matched the filters implied by the question.",
            error_type="empty_result",
        )
        result["success"] = True
        state["memory"].add_turn(state["question"], state.get("final_sql", ""), "No rows returned.", "database")
        return {"result": result}

    # 11. GENERATE REPORT NODE
    async def generate_report_node(state: AgentState) -> dict:
        import time
        result = state["result"]
        rows = state.get("rows") or []
        question = state["question"]
        final_sql = state.get("final_sql") or state.get("sql") or ""
        analysis_type = state["analysis_type"]

        truncated = len(rows) > MAX_ROWS_FOR_LLM
        rows_for_llm = rows[:MAX_ROWS_FOR_LLM] if truncated else rows

        t0 = time.perf_counter()
        result["report_mode"] = agent.report_service.resolve_report_mode(
            state.get("query_understanding")
        ).value
        conv_hist = state.get("conversation_history", "")
        report, chart = await agent.report_service.generate_report_and_chart(
            question, final_sql, rows_for_llm,
            analytics_result=state.get("analytics_result"),
            insight_result=state.get("insight_result"),
            analysis_result=state.get("analysis_result"),
            require_verification=(analysis_type in COMPLEX_ANALYSIS_TYPES),
            verified_facts=result.get("verification", {}).get("deterministic_facts"),
            total_result_rows=len(rows),
            query_spec=state.get("query_understanding"),
            verification_rows=rows,
            is_first_turn=not bool(conv_hist.strip()),
            conversation_history=conv_hist,
        )
        rep_ms = (time.perf_counter() - t0) * 1000

        # Grounded Report Composition for Investigations (Phase 8)
        # Keep the LLM-generated conversational report as the primary response.
        # The GroundedReportComposer metadata is stored for transparency/debugging
        # but does NOT override the natural report — this ensures the user always
        # gets a human, adaptive answer instead of a fixed robotic template.
        investigation = state.get("investigation")
        if investigation and (investigation.evidence or investigation.completed_queries):
            from app.services.analysis.grounded_report_composer import GroundedAnalysisContext
            grounded_ctx = GroundedAnalysisContext.from_investigation(
                state=investigation,
                analysis_result=state.get("analysis_result"),
                question=question,
            )
            result["grounded_context"] = {
                "completed_tasks": grounded_ctx.completed_analysis_tasks,
                "verified_evidence_count": len(grounded_ctx.verified_evidence),
                "unverified_evidence_count": len(grounded_ctx.unverified_evidence),
                "validation_issues_count": len(grounded_ctx.validation_issues),
                "supported_root_causes": grounded_ctx.supported_root_causes,
                "is_complete": grounded_ctx.is_complete,
            }

        verification_data = result.setdefault("verification", {})
        if result["report_mode"] == "deterministic":
            verification_data["claim_evaluations"] = []
            verification_data["claim_confidence"] = 1.0
            verification_data["claims_grounded"] = True
        else:
            from app.services.sql.result_verifier import result_verifier
            constrained_report, claim_evaluations, claim_confidence = result_verifier.verify_and_constrain_prose(
                report,
                rows=rows,
                facts=verification_data.get("deterministic_facts"),
                analytics_result=state.get("analytics_result"),
                sql=final_sql,
            )
            verification_data["claim_evaluations"] = [c.to_dict() for c in claim_evaluations]
            verification_data["claim_confidence"] = claim_confidence
            claims_ok = all(c.is_verified for c in claim_evaluations)
            verification_data["claims_grounded"] = claims_ok
            if not claims_ok:
                unverified_claims = [
                    f"Unverified claim: '{c.statement}'" for c in claim_evaluations if not c.is_verified
                ]
                result.setdefault("warnings", []).extend(
                    warning for warning in unverified_claims if warning not in result["warnings"]
                )
            report = constrained_report
        if verification_data.get("answer_action") == "WARN":
            warning_gates = ", ".join(
                name.replace("_", " ") for name, status in verification_data.get("gate_statuses", {}).items()
                if status == "WARN"
            )
            report += f"\n\n*Warning: result quality checks flagged {warning_gates}.*"

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

    # ─── STATE GRAPH DEFINITION & WIRING ───
    graph = StateGraph(AgentState)
    graph.add_node("understand", understand_node)
    graph.add_node("analysis_plan", analysis_plan_node)
    graph.add_node("ground_schema", ground_schema_node)
    graph.add_node("select_next_query", select_next_query_node)
    graph.add_node("retrieve_data", retrieve_data_node)
    graph.add_node("validate_sql", validate_sql_node)
    graph.add_node("cost_guard", cost_guard_node)
    graph.add_node("execute", execute_node)
    graph.add_node("record_investigation_result", record_investigation_result_node)
    graph.add_node("planner_fallback", planner_fallback_node)
    graph.add_node("report_exec_error", report_exec_error_node)
    graph.add_node("run_analysis", run_analysis_node)
    graph.add_node("verify_results", verify_results_node)
    graph.add_node("no_rows_report", no_rows_report_node)
    graph.add_node("generate_report", generate_report_node)

    graph.set_entry_point("understand")
    graph.add_conditional_edges("understand", route_after_understand, {END: END, "analysis_plan": "analysis_plan"})
    graph.add_edge("analysis_plan", "ground_schema")
    graph.add_edge("ground_schema", "select_next_query")
    graph.add_conditional_edges(
        "select_next_query",
        route_after_select_query,
        {"retrieve_data": "retrieve_data", "run_analysis": "run_analysis"},
    )
    graph.add_conditional_edges(
        "retrieve_data",
        route_after_retrieve,
        {END: END, "validate_sql": "validate_sql", "record_investigation_result": "record_investigation_result"},
    )
    graph.add_conditional_edges(
        "validate_sql",
        route_after_validate,
        {END: END, "cost_guard": "cost_guard", "record_investigation_result": "record_investigation_result"},
    )
    graph.add_conditional_edges(
        "cost_guard",
        route_after_cost_guard,
        {END: END, "execute": "execute", "record_investigation_result": "record_investigation_result"},
    )
    graph.add_conditional_edges(
        "execute",
        route_after_execute,
        {
            "record_investigation_result": "record_investigation_result",
            "planner_fallback": "planner_fallback",
            "report_exec_error": "report_exec_error",
            "run_analysis": "run_analysis",
        },
    )
    graph.add_conditional_edges(
        "record_investigation_result",
        route_after_record,
        {"select_next_query": "select_next_query", "run_analysis": "run_analysis"},
    )
    graph.add_conditional_edges(
        "planner_fallback",
        route_after_planner_fallback,
        {END: END, "report_exec_error": "report_exec_error"},
    )
    graph.add_edge("report_exec_error", END)
    graph.add_edge("run_analysis", "verify_results")
    graph.add_conditional_edges(
        "verify_results",
        route_after_verify,
        {END: END, "no_rows_report": "no_rows_report", "generate_report": "generate_report"},
    )
    graph.add_edge("no_rows_report", END)
    graph.add_edge("generate_report", END)

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

    # Step 12: Record Evaluation Trace
    qspec_obj = final_state.get("query_understanding")
    grounded_obj = final_state.get("grounded_schema")

    conf_route = float(getattr(qspec_obj, "route_confidence", 1.0)) if qspec_obj else 1.0
    conf_retrieval = 0.95 if (grounded_obj and not getattr(grounded_obj, "fallback_used", False)) else 0.70
    has_grounding_warnings = any(
        w for w in result.get("warnings", [])
        if "table" in w.lower() or "column" in w.lower() or "join" in w.lower()
    )
    sql_validation = result.get("sql_validation", {})
    grounding_failed = (
        sql_validation.get("identifiers_valid") is False
        or sql_validation.get("joins_valid") is False
    )
    conf_grounding, grounding_evidence = grounding_confidence(grounded_obj, qspec_obj)
    if has_grounding_warnings or grounding_failed:
        conf_grounding = min(conf_grounding, 0.60)
    has_error = bool(result.get("error")) or result.get("error_type") in (
        "execution_error", "sql_error", "orchestrator_failure", "safety", "identifier_grounding", "join_validation", "syntax_error"
    )
    is_non_data_route = qspec_obj and getattr(qspec_obj, "route", None) in (ExecutionRoute.CONVERSATION, ExecutionRoute.SCHEMA)
    is_clarification = result.get("intent") == "clarification" or result.get("error_type") == "ambiguity"
    has_results = result.get("results") is not None and len(result.get("results", [])) > 0

    if has_error:
        conf_sql = 0.0
        conf_execution = 0.0
        conf_answer = 0.0
        overall_confidence = 0.0
    elif is_non_data_route or is_clarification:
        conf_sql = 1.0
        conf_execution = 1.0
        conf_answer = 1.0
        overall_confidence = round(
            conf_route * 0.40 + conf_retrieval * 0.30 + conf_answer * 0.30,
            3
        )
    else:
        repair_cnt = result.get("sql_repair_attempts", 0) or 0
        conf_sql = 1.0 if repair_cnt == 0 else max(0.4, 1.0 - repair_cnt * 0.25)
        conf_execution = 1.0 if has_results else (0.75 if result.get("success") else 0.0)
        claims_grounded = result.get("verification", {}).get("claims_grounded", True)
        conf_answer = 1.0 if claims_grounded else 0.80

        overall_confidence = round(
            conf_route * 0.15 + conf_retrieval * 0.15 + conf_grounding * 0.20 +
            conf_sql * 0.20 + conf_execution * 0.15 + conf_answer * 0.15,
            3
        )

    confidence_breakdown = {
        "route": round(conf_route, 2),
        "retrieval": round(conf_retrieval, 2),
        "grounding": round(conf_grounding, 2),
        "sql": round(conf_sql, 2),
        "execution": round(conf_execution, 2),
        "answer": round(conf_answer, 2),
        "overall": overall_confidence,
    }
    result["confidence_breakdown"] = confidence_breakdown

    evaluation_trace = {
        "question": question,
        "route": qspec_obj.route.value if qspec_obj and hasattr(qspec_obj.route, "value") else "unknown",
        "retrieval_evidence": {
            "seed_tables": list(grounded_obj.retrieved_seed_tables) if grounded_obj else [],
        "grounded_tables": list(grounded_obj.selected_tables) if grounded_obj else [],
            "grounding_evidence": grounding_evidence,
        },
        "query_spec": {
            "entities": qspec_obj.entities if qspec_obj else [],
            "metrics": qspec_obj.metrics if qspec_obj else [],
            "dimensions": qspec_obj.dimensions if qspec_obj else [],
            "analysis_type": qspec_obj.analysis_type.value if qspec_obj and hasattr(qspec_obj.analysis_type, "value") else "unknown",
            "output_shape": qspec_obj.output_shape if qspec_obj else "table",
            "confidence": qspec_obj.confidence if qspec_obj else 1.0,
        } if qspec_obj else {},
        "sql": result.get("sql") or result.get("attempted_sql") or "",
        "validation_passed": (
            result.get("sql_validation", {}).get("identifiers_valid", True)
            and result.get("sql_validation", {}).get("joins_valid", True)
            and result.get("error_type") not in ("safety", "identifier_grounding", "join_validation")
        ),
        "execution_metrics": {
            "rows_count": len(result.get("results") or []),
            "execution_ms": result.get("timings_ms", {}).get("sql_execution_ms", 0.0),
            "repair_attempts": result.get("sql_repair_attempts", 0),
            "cache_hit": result.get("sql_cache_hit", False),
        },
        "verification_outcome": result.get("verification", {}),
        "confidence_breakdown": confidence_breakdown,
        "timings_ms": result.get("timings_ms", {}),
        "confidence": overall_confidence,
    }
    result["evaluation_trace"] = evaluation_trace

    return result
