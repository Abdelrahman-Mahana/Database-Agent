"""Module for planning and executing multi-step question decomposition."""
import json
import logging
import re
from typing import Any, List, Dict

from sqlalchemy.orm import Session
from langchain_core.prompts import PromptTemplate

from app.llm.prompts import DECOMPOSE_QUESTION_TEMPLATE, SUB_QUESTION_SQL_TEMPLATE, SYNTHESIS_TEMPLATE
from app.utils.validator import validate_sql, sanitize_query, transpile_sql_to_dialect, get_target_dialect
from app.utils.text_processor import extract_json_text, build_result_summary, build_temporal_grounding_hint, filter_schema_by_query
from app.services.sql_service import SQLExecutor
from app.sql.control_gate import SQLControlGate
from app.semantic.query_spec_builder import QuerySpecBuilder
from app.security.data_masking import mask_sensitive_columns
from app.config.settings import settings
from app.sql.result_verifier import result_verifier

logger = logging.getLogger(__name__)


class Planner:
    """Decomposes complex queries, executes sub-questions iteratively, and synthesizes reports."""

    def __init__(self, primary_llm, fast_llm):
        self.primary_llm = primary_llm
        self.fast_llm = fast_llm
        self.sql_executor = SQLExecutor()

        # Create chains using LCEL
        self.decompose_chain = (
            PromptTemplate(
                input_variables=["schema", "question", "conversation_history"],
                template=DECOMPOSE_QUESTION_TEMPLATE
            )
            | self.fast_llm
        )

        self.sub_question_chain = (
            PromptTemplate(
                input_variables=["schema", "context", "sub_question"],
                template=SUB_QUESTION_SQL_TEMPLATE
            )
            | self.primary_llm
        )

        self.synthesis_chain = (
            PromptTemplate(
                input_variables=["question", "context", "conversation_history"],
                template=SYNTHESIS_TEMPLATE
            )
            | self.fast_llm
        )

    async def decompose_question(self, question: str, schema_text: str, conversation_history: str = "") -> List[str]:
        """Decompose a complex question into sub-questions."""
        try:
            decompose_resp = await self.decompose_chain.ainvoke({
                "schema": schema_text,
                "question": question,
                "conversation_history": conversation_history
            })
            plan_json = extract_json_text(decompose_resp.content)
            plan_data = json.loads(plan_json)
            return plan_data.get("steps", [])
        except Exception as e:
            logger.warning("Failed to decompose question, falling back to single step. Error: %s", e)
            return []

    async def execute_plan(
        self,
        question: str,
        plan_steps: List[str],
        schema_text: str,
        db: Session,
        conversation_history: str,
        sql_generator,
        report_service,
        memory,
        catalog=None,
        raw_schema: Dict[str, Any] | None = None,
        db_ctx=None,
    ) -> Dict[str, Any] | None:
        """Execute a multi-step plan, querying the DB and synthesizing the final report."""
        if not plan_steps or len(plan_steps) < 2:
            return None

        logger.info("Executing plan with %d steps: %s", len(plan_steps), plan_steps)
        step_contexts = []
        final_sql_statements = []
        execution_results = []
        step_facts = []
        gate = SQLControlGate()
        spec_builder = QuerySpecBuilder()
        failed_step_number = None
        failure_reason = None
        
        for idx, step in enumerate(plan_steps):
            step_context_str = "\n".join(
                f"Step {i+1}: Q: {s['q']} -> SQL: {s['sql']} -> Results Summary: {s['summary']}"
                for i, s in enumerate(step_contexts)
            )
            
            hint = build_temporal_grounding_hint(step, schema_text)
            context_for_prompt = step_context_str or "No prior steps."
            if hint:
                context_for_prompt = f"{hint}\n{context_for_prompt}"

            try:
                # Filter schema based on tables mentioned in this specific sub-question
                mini_schema = filter_schema_by_query(schema_text, step)
                
                sub_resp = await self.sub_question_chain.ainvoke({
                    "schema": mini_schema,
                    "context": context_for_prompt,
                    "sub_question": step
                })
                sub_sql = sanitize_query(sql_generator.extract_sql(sub_resp.content))
                sub_sql = transpile_sql_to_dialect(sub_sql, get_target_dialect())
            except Exception as e:
                logger.error("Failed to generate SQL for step: %s. Error: %s", step, e)
                failed_step_number = idx + 1
                failure_reason = f"Could not generate SQL for step {idx + 1}: {e}"
                break
                
            # Each plan step is its own query, so create a scoped semantic spec
            # and submit the SQL to the same control gate as the main pipeline.
            try:
                # Use the canonical async builder, not its deterministic-only
                # compatibility entrypoint. This keeps feature policy (such as
                # use_llm_understanding) identical for root and planned SQL.
                step_spec = await spec_builder.build_spec_async(
                    step, db_ctx=db_ctx, catalog=catalog
                )
            except Exception as e:
                logger.warning("Could not build semantic specification for planner step %d: %s", idx + 1, e)
                failed_step_number = idx + 1
                failure_reason = f"Could not validate the semantic intent of step {idx + 1}: {e}"
                break
            gate_result = gate.evaluate(
                sub_sql, query_spec=step_spec, catalog=catalog,
                raw_schema=raw_schema, db=db,
            )
            if not gate_result.allowed:
                logger.warning("Planner step blocked by SQL control gate: %s", gate_result.reason)
                failed_step_number = idx + 1
                failure_reason = f"Step {idx + 1} did not pass the SQL control gate: {gate_result.reason}"
                break
                
            try:
                rows = self.sql_executor.execute(sub_sql, db)
                if settings.enable_data_masking and rows:
                    rows, _ = mask_sensitive_columns(rows, settings.extra_masked_column_patterns)
                verification = result_verifier.verify(
                    rows, query_spec=step_spec, sql=sub_sql,
                    validation_status=gate_result.validation_status, catalog=catalog,
                )
                if verification.answer_action == "FAIL":
                    logger.warning("Planner step blocked by result verification: %s", verification.gate_statuses)
                    failed_step_number = idx + 1
                    failure_reason = f"Step {idx + 1} did not pass result verification."
                    break
                step_facts.extend(verification.deterministic_facts)
                summary = f"Returned {len(rows)} verified rows. Sample values: {rows[:3]}" if rows else "No rows returned."
                step_contexts.append({
                    "q": step,
                    "sql": sub_sql,
                    "summary": summary
                })
                final_sql_statements.append(sub_sql)
                execution_results = rows
            except Exception as e:
                logger.warning("Step execution failed: %s. Error: %s", sub_sql, e)
                failed_step_number = idx + 1
                failure_reason = f"Step {idx + 1} failed during execution: {e}"
                break
        
        # A partial plan must never be synthesized as if it were a complete
        # answer.  Any blocked/failed step returns control to the canonical
        # failure path instead.
        if len(step_contexts) != len(plan_steps):
            plan_status = "PARTIAL" if step_contexts else "FAILED"
            return {
                "success": False,
                "plan_status": plan_status,
                "completed_steps": len(step_contexts),
                "required_steps": len(plan_steps),
                "failed_step": failed_step_number or len(step_contexts) + 1,
                "error_type": "planner_incomplete",
                "error": failure_reason or "The plan did not complete all required steps.",
            }

        if step_contexts:
            final_context_str = "\n".join(
                f"Step {i+1}: Q: {s['q']} -> SQL: {s['sql']} -> Results: {s['summary']}"
                for i, s in enumerate(step_contexts)
            )
            
            try:
                synthesis_resp = await self.synthesis_chain.ainvoke({
                    "question": question,
                    "context": final_context_str,
                    "conversation_history": conversation_history
                })
                # Claim verification is mandatory for planner synthesis too.
                report, claim_evaluations, claim_confidence = result_verifier.verify_and_constrain_prose(
                    synthesis_resp.content,
                    rows=execution_results,
                    facts=step_facts,
                    sql=final_sql_statements[-1] if final_sql_statements else "",
                )
                summary_str = build_result_summary(execution_results)
                memory.add_turn(question, final_sql_statements[-1] if final_sql_statements else "", summary_str, "database")
                
                chart = await report_service.suggest_chart(
                    question, 
                    final_sql_statements[-1] if final_sql_statements else "",
                    execution_results[:100]
                )
                
                return {
                    "question": question,
                    "sql": final_sql_statements[-1] if final_sql_statements else "",
                    "results": execution_results[:100],
                    "report": report,
                    "chart_suggestion": chart,
                    "success": True,
                    "plan_status": "COMPLETE",
                    "report_mode": "synthesis",
                    "completed_steps": len(step_contexts),
                    "required_steps": len(plan_steps),
                    "error": None,
                    "attempted_sql": ";\n\n".join(final_sql_statements),
                    "error_type": None,
                    "suggestions": [],
                    "intent": "database",
                    "verification": {
                        "deterministic_facts": [fact.to_dict() for fact in step_facts],
                        "claim_evaluations": [claim.to_dict() for claim in claim_evaluations],
                        "claim_confidence": claim_confidence,
                        "claims_grounded": all(claim.is_verified for claim in claim_evaluations),
                    },
                }
            except Exception as e:
                logger.exception("Synthesis failed. Falling back to single step flow.")
                return {
                    "success": False,
                    "plan_status": "FAILED",
                    "completed_steps": len(step_contexts),
                    "required_steps": len(plan_steps),
                    "error_type": "planner_synthesis",
                    "error": f"The plan completed but report synthesis failed: {e}",
                }
        return {"success": False, "plan_status": "FAILED", "error_type": "planner_incomplete", "error": "No plan steps completed."}
