"""Module for planning and executing multi-step question decomposition."""
import json
import logging
import re
from typing import Any, List, Dict

from sqlalchemy.orm import Session
from langchain_core.prompts import PromptTemplate

from app.llm.prompts import DECOMPOSE_QUESTION_TEMPLATE, SUB_QUESTION_SQL_TEMPLATE, SYNTHESIS_TEMPLATE
from app.utils.validator import validate_sql, sanitize_query, transpile_sql_to_dialect, get_target_dialect
from app.utils.text_processor import extract_json_text, build_result_summary, build_temporal_grounding_hint
from app.services.sql_service import SQLExecutor

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
        memory
    ) -> Dict[str, Any] | None:
        """Execute a multi-step plan, querying the DB and synthesizing the final report."""
        if not plan_steps or len(plan_steps) < 2:
            return None

        logger.info("Executing plan with %d steps: %s", len(plan_steps), plan_steps)
        step_contexts = []
        final_sql_statements = []
        execution_results = []
        
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
                sub_resp = await self.sub_question_chain.ainvoke({
                    "schema": schema_text,
                    "context": context_for_prompt,
                    "sub_question": step
                })
                sub_sql = sanitize_query(sql_generator.extract_sql(sub_resp.content))
                sub_sql = transpile_sql_to_dialect(sub_sql, get_target_dialect())
            except Exception as e:
                logger.error("Failed to generate SQL for step: %s. Error: %s", step, e)
                break
                
            val = validate_sql(sub_sql)
            if not val["valid"]:
                logger.warning("Step SQL validation failed: %s. Reason: %s", sub_sql, val["reason"])
                break
                
            try:
                rows = self.sql_executor.execute(sub_sql, db)
                summary = f"Returned {len(rows)} rows. Sample values: {rows[:3]}" if rows else "No rows returned."
                step_contexts.append({
                    "q": step,
                    "sql": sub_sql,
                    "summary": summary
                })
                final_sql_statements.append(sub_sql)
                execution_results = rows
            except Exception as e:
                logger.warning("Step execution failed: %s. Error: %s", sub_sql, e)
                break
        
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
                report = synthesis_resp.content
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
                    "error": None,
                    "attempted_sql": ";\n\n".join(final_sql_statements),
                    "error_type": None,
                    "suggestions": [],
                    "intent": "database",
                }
            except Exception as e:
                logger.exception("Synthesis failed. Falling back to single step flow.")
                return None
        return None
