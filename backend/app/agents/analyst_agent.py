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

from app.agents.schema_explorer import SchemaExplorer
from app.agents.sql_generator import SQLGenerator
from app.agents.planner import Planner
from app.schema_grounding.grounding_engine import SchemaGroundingEngine
from app.schema_grounding.confidence import grounding_confidence
from app.analytics import AnalyticsEngine, InsightEngine
from app.semantic.synonyms import resolve_synonyms
from app.semantic.query_spec_builder import QuerySpecBuilder
from app.semantic.models import IntentType, ExecutionRoute, QuerySpec
from app.schema_catalog.catalog_builder import CatalogBuilder
from app.utils.cost_router import should_use_self_consistency, choose_sql_generation_tier
from app.config.settings import settings
from app.security.cost_guard import check_query_cost, cost_guard_failure_result
from app.security.data_masking import mask_sensitive_columns
from app.sql.control_gate import SQLControlGate

# --- Tunables -----------------------------------------------------------
LLM_TEMPERATURE = 0.1          # low temperature: we want deterministic, correct SQL
MAX_FIX_ATTEMPTS = getattr(settings, "max_fix_attempts", 1)  # bounded auto-repair attempts
MAX_ROWS_FOR_LLM = 200         # cap rows sent to the report/chart LLM calls (cost + context safety)


class AnalystAgent:
    """
    Canonical End-to-End Database Analyst Agent implementing the unified orchestration contract:
    
    Canonical Pipeline (one path per deployment — selected by use_langgraph_orchestrator):
      - LangGraph path:  graph_orchestrator.run_graph_ask()
      - Service path:    _run_service_pipeline() (step-by-step orchestration below)

    Stage-level fallbacks (e.g. Planner after single-SQL failure) live inside the
    active pipeline only. There is no cross-architecture fallback.
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
        self.schema_explorer = SchemaExplorer()
        self.sql_generator = SQLGenerator(self.primary_llm, self.self_consistency_llm, fast_llm=self.fast_llm)
        self.query_spec_builder = QuerySpecBuilder(self.fast_llm)
        self.analytics_engine = AnalyticsEngine()
        self.insight_engine = InsightEngine()
        self._graph = None

    def get_or_build_graph(self):
        """Lazily build+cache the LangGraph orchestrator for this agent instance."""
        if self._graph is None:
            from app.agents.graph_orchestrator import build_analyst_graph
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
        """Canonical LangGraph orchestration path. Failures surface explicitly — no legacy fallback."""
        import time
        from app.agents.graph_orchestrator import run_graph_ask

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
        memory,
        conversation_history: str,
        query_spec: QuerySpec,
        db_ctx,
        full_schema: dict,
        catalog,
        req_start: float,
        timings_ms: dict[str, float],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Canonical step-by-step service pipeline."""
        return await self._execute_service_pipeline(
            question, db, memory, conversation_history,
            query_spec, db_ctx, full_schema, catalog,
            req_start, timings_ms, result,
        )

    async def _execute_service_pipeline(
        self,
        question: str,
        db: Session,
        memory,
        conversation_history: str,
        query_spec: QuerySpec,
        db_ctx,
        full_schema: dict,
        catalog,
        req_start: float,
        timings_ms: dict[str, float],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Core service-pipeline stages. Stage-level fallbacks only (e.g. Planner)."""
        import time
        result["orchestrator"] = "service"

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
                result["error_type"] = "unanswerable"
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

            # Step 3: Validate SQL safety & AST identifier grounding & join path verification
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

            from app.sql.validator import sql_validator
            ident_ok, ident_warnings = sql_validator.verify_sql_identifiers(sql, catalog=catalog, raw_schema=full_schema)
            join_ok, join_warnings = sql_validator.verify_sql_joins(sql, catalog=catalog)
            qspec_ok, qspec_warnings = sql_validator.verify_query_spec_alignment(sql, query_spec=query_spec)

            for w in ident_warnings + join_warnings + qspec_warnings:
                if w not in result["warnings"]:
                    result["warnings"].append(w)
            result["sql_validation"] = {
                "safety_valid": True,
                "identifiers_valid": ident_ok,
                "joins_valid": join_ok,
                "alignment_valid": qspec_ok,
            }
            # Identifier, join, and QuerySpec checks are retained as useful
            # generation diagnostics, but the canonical SQLControlGate below
            # is the sole execution authority.  That matters for repaired SQL:
            # the final candidate (not this initial draft) must be validated.
            # SQLGenerator applies this gate to the initial SQL, cache hits,
            # and every repair before execution.
            result["pre_execution_validation"] = dict(result["sql_validation"])

            # Step 3.5: Multi-layer cost pre-check (AST + Catalog + DB EXPLAIN)
            if settings.enable_cost_guard:
                try:
                    cost_check = check_query_cost(
                        sql=sql,
                        catalog=catalog,
                        max_unfiltered_rows=settings.cost_guard_max_unfiltered_rows,
                        db=db,
                        max_estimated_rows=settings.cost_guard_max_estimated_rows,
                    )
                except Exception as cost_err:
                    cost_check = cost_guard_failure_result(
                        sql,
                        catalog=catalog,
                        max_unfiltered_rows=settings.cost_guard_max_unfiltered_rows,
                        error=cost_err,
                    )
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
                pre_execution_gate=lambda candidate: SQLControlGate().evaluate(
                    candidate, query_spec=query_spec, catalog=catalog, raw_schema=full_schema, db=db,
                ),
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
                                memory=memory,
                                catalog=catalog,
                                raw_schema=full_schema,
                                db_ctx=db_ctx,
                            )
                            if plan_result and plan_result.get("success"):
                                timings_ms["total_request_time_ms"] = round((time.perf_counter() - req_start) * 1000, 2)
                                plan_result["timings_ms"] = timings_ms
                                plan_result["schema_metrics"] = schema_metrics
                                return plan_result
                            if plan_result:
                                result["plan_status"] = plan_result.get("plan_status")
                                result["plan_completed_steps"] = plan_result.get("completed_steps", 0)
                                result["plan_required_steps"] = plan_result.get("required_steps", len(plan_steps))
                                exec_error = plan_result.get("error", exec_error)
                                error_type = plan_result.get("error_type", "planner_incomplete")
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
            # A successful SQLGenerator execution means the final candidate
            # cleared SQLControlGate.  Preserve the initial diagnostics above,
            # while reporting the authoritative status for the executed SQL.
            result["sql_validation"] = {
                "safety_valid": True,
                "identifiers_valid": True,
                "joins_valid": True,
                "alignment_valid": True,
            }

            # Phase 5: Data masking
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

            # Step 10: Verify Results against QuerySpec (Cardinality, Nulls, Duplicates)
            from app.sql.result_verifier import result_verifier
            verification = result_verifier.verify(
                rows, query_spec=query_spec, sql=final_sql,
                validation_status=result.get("sql_validation"),
                catalog=catalog,
            )
            result["verification"] = verification.to_dict()
            if verification.warnings:
                for w in verification.warnings:
                    if w not in result["warnings"]:
                        result["warnings"].append(w)
            if verification.answer_action == "FAIL":
                result["error_type"] = "result_verification"
                result["error"] = "Result verification failed required quality gates."
                result["report"] = await self.report_service.generate_no_answer_response(
                    question=question,
                    situation="The query result did not pass the required quality gates.",
                    reason="; ".join(
                        f"{name}: {status}" for name, status in verification.gate_statuses.items()
                        if status == "FAIL"
                    ),
                    table_names=list(full_schema.keys()),
                )
                result["timings_ms"] = timings_ms
                return result

            # Step 11: Compose Answer & Insights (Deterministic templates + constrained phrasing)
            if not rows:
                result["error_type"] = "empty_result"
                result["report"] = await self.report_service.generate_no_answer_response(
                    question=question,
                    situation="The query ran successfully but returned no matching rows.",
                    reason="No records matched the filters implied by the question.",
                    table_names=list(full_schema.keys()),
                )
                if verification.answer_action == "WARN":
                    result["report"] += "\n\n*Warning: result quality checks flagged result cardinality.*"
                result["success"] = True
                memory.add_turn(question, final_sql, "No rows returned.", "database")
                timings_ms["total_request_time_ms"] = round((time.perf_counter() - req_start) * 1000, 2)
                result["timings_ms"] = timings_ms
                return result

            truncated = len(rows) > MAX_ROWS_FOR_LLM
            rows_for_llm = rows[:MAX_ROWS_FOR_LLM] if truncated else rows

            t0 = time.perf_counter()
            result["report_mode"] = self.report_service.resolve_report_mode(query_spec).value
            report, chart = await self.report_service.generate_report_and_chart(
                question, final_sql, rows_for_llm,
                analytics_result=analytics_result,
                insight_result=insight_result,
                require_verification=(analysis_type in COMPLEX_ANALYSIS_TYPES),
                verified_facts=verification.deterministic_facts,
                total_result_rows=len(rows),
                query_spec=query_spec,
                verification_rows=rows,
            )
            step_duration = round((time.perf_counter() - t0) * 1000, 2)
            timings_ms["report_generation_ms"] = step_duration
            timings_ms["chart_suggestion_ms"] = 0.0

            # Step 11.5: Result-to-Answer Claim Checker & Prose Constraining.
            # Deterministic reports are rendered directly from verified rows,
            # so re-parsing their bullets/IDs as free prose only hurts UX.
            if result["report_mode"] == "deterministic":
                result["verification"]["claim_evaluations"] = []
                result["verification"]["claim_confidence"] = 1.0
                result["verification"]["claims_grounded"] = True
            else:
                constrained_report, claim_evaluations, claim_confidence = result_verifier.verify_and_constrain_prose(
                    report, rows=rows, facts=verification.deterministic_facts,
                    analytics_result=analytics_result, sql=final_sql,
                )
                result["verification"]["claim_evaluations"] = [c.to_dict() for c in claim_evaluations]
                result["verification"]["claim_confidence"] = claim_confidence
                claims_ok = all(c.is_verified for c in claim_evaluations)
                result["verification"]["claims_grounded"] = claims_ok
                if not claims_ok:
                    unverified_claims = [f"Unverified claim: '{c.statement}'" for c in claim_evaluations if not c.is_verified]
                    result["verification"]["unverified_claims"] = unverified_claims
                    for c_warn in unverified_claims:
                        result["warnings"].append(c_warn)

                report = constrained_report
            if verification.answer_action == "WARN":
                warning_gates = ", ".join(
                    name.replace("_", " ") for name, status in verification.gate_statuses.items()
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

            memory.add_turn(question, final_sql, build_result_summary(rows), "database")
            result["success"] = True

        except Exception as e:
            logger.exception("AnalystAgent service pipeline failed for question=%r", question)
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

        # Step 12: Record Evaluation & Audit Trace with Confidence Decomposition
        grounded_obj = locals().get("grounded_schema")
        qspec_obj = query_spec
        val_obj = locals().get("validation")

        conf_route = float(getattr(qspec_obj, "route_confidence", 1.0)) if qspec_obj else 1.0
        conf_retrieval = 0.95 if (grounded_obj and not getattr(grounded_obj, "fallback_used", False)) else 0.70
        conf_grounding, grounding_evidence = grounding_confidence(grounded_obj, qspec_obj)
        if locals().get("ident_warnings"):
            conf_grounding = min(conf_grounding, 0.60)
        repair_cnt = result.get("sql_repair_attempts", 0) or 0
        conf_sql = 1.0 if repair_cnt == 0 else max(0.4, 1.0 - repair_cnt * 0.25)
        conf_execution = 1.0 if result.get("results") else (0.75 if result.get("success") else 0.0)
        claim_conf_val = result.get("verification", {}).get("claim_confidence")
        conf_answer = claim_conf_val if claim_conf_val is not None else (1.0 if result.get("verification", {}).get("claims_grounded", True) else 0.80)

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
            "validation_passed": val_obj.get("valid", True) if val_obj else True,
            "execution_metrics": {
                "rows_count": len(result.get("results") or []),
                "execution_ms": timings_ms.get("sql_execution_ms", 0.0),
                "repair_attempts": result.get("sql_repair_attempts", 0),
                "cache_hit": result.get("sql_cache_hit", False),
            },
            "verification_outcome": result.get("verification", {}),
            "confidence_breakdown": confidence_breakdown,
            "timings_ms": timings_ms,
            "confidence": overall_confidence,
        }
        result["evaluation_trace"] = evaluation_trace

        logger.info(
            "Stage timings (ms): %s | Schema metrics: %s | LLM calls: %d",
            timings_ms, result.get("schema_metrics", {}), len(trace),
        )
        return result

    async def ask(self, question: str, db: Session, session_id: str | None = None) -> dict[str, Any]:
        """
        Process a natural language question and return an analyst report.

        Routes to exactly one canonical orchestrator (LangGraph or service pipeline).
        Early exits handle conversation/schema intents before orchestrator selection.
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
            schema_resp = self.schema_explorer.handle_schema_exploration(question)
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

        if settings.use_langgraph_orchestrator:
            return await self._run_graph_pipeline(question, db, memory, conversation_history, req_start)

        return await self._run_service_pipeline(
            question, db, memory, conversation_history,
            query_spec, db_ctx, full_schema, catalog,
            req_start, timings_ms, result,
        )
