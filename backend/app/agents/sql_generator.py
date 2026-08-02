"""Module for orchestrating SQL generation, validation, execution, and repair."""
import asyncio
import logging
import time
from typing import Any, List, Tuple

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.sql_service import SchemaService, SQLExecutor
from app.utils.cache import get_cached_sql, set_cached_sql, get_cached_results, set_cached_results
from app.utils.text_processor import extract_sql, normalize_sql
from app.sql import (
    SQLPromptBuilder,
    GroundingEngine,
    SQLValidator,
    SQLRepairEngine,
)

logger = logging.getLogger(__name__)


class SQLGenerator:
    """Orchestrates query generation, self-consistency candidates selection, grounding, and SQL repair."""

    def __init__(self, primary_llm, self_consistency_llm, fast_llm=None):
        self.primary_llm = primary_llm
        self.self_consistency_llm = self_consistency_llm
        self.fast_llm = fast_llm
        self.schema_service = SchemaService()
        self.sql_executor = SQLExecutor()

        # Modular sub-components
        self.prompt_builder = SQLPromptBuilder()
        self.grounding_engine = GroundingEngine()
        self.validator = SQLValidator()
        self.repair_engine = SQLRepairEngine(self.primary_llm)

        # LCEL chains
        self.sql_generation_chain = self.prompt_builder.zero_shot_template | self.primary_llm
        self.self_consistency_chain = self.prompt_builder.zero_shot_template | self.self_consistency_llm
        # Phase 6 (rebuild plan): only built if a fast_llm was actually
        # passed in - existing callers that construct SQLGenerator with just
        # two args (tests, older code) get None here and simply never route
        # to it (see generate_sql's use_fast_model handling below).
        self.fast_generation_chain = (
            self.prompt_builder.zero_shot_template | self.fast_llm if self.fast_llm is not None else None
        )

    async def generate_sql(
        self,
        question: str,
        schema_text: str,
        db: Session,
        conversation_history: str = "",
        use_self_consistency: bool | None = None,
        use_fast_model: bool = False,
    ) -> str:
        """Generate and normalize a SQL query for the user's question using LangChain and self-consistency voting.

        `use_self_consistency`: per-question override (see app.utils.cost_router).
        None falls back to the static global `settings.enable_self_consistency`
        switch for backward compatibility.
        `use_fast_model`: Phase 6 per-question model-tier routing (see
        app.utils.cost_router.choose_sql_generation_tier). Only takes effect
        for the single-candidate path below - self-consistency, when used,
        always stays on the primary/self-consistency tier (voting on the
        cheap model would defeat its purpose) - and only if this instance
        was actually constructed with a fast_llm.
        """
        # 1. Check generated SQL cache first
        cached_sql = get_cached_sql(question, schema_text)
        if cached_sql:
            return cached_sql

        use_voting = settings.enable_self_consistency if use_self_consistency is None else use_self_consistency

        if not use_voting or settings.sql_candidates <= 1:
            # Single candidate generation
            start_time = time.time()
            payload = self.prompt_builder.build_generation_input(
                schema_text=schema_text,
                question=question,
                conversation_history=conversation_history,
            )
            chain = (
                self.fast_generation_chain
                if (use_fast_model and self.fast_generation_chain is not None)
                else self.sql_generation_chain
            )
            response = await chain.ainvoke(payload)
            duration_ms = (time.time() - start_time) * 1000

            sql_response = response.content
            raw_sql = self.validator.sanitize_and_extract(sql_response)
            final_sql = self.validator.transpile(raw_sql)
            set_cached_sql(question, schema_text, final_sql)

            tokens = response.response_metadata.get("token_usage", {}) if hasattr(response, "response_metadata") else {}
            prompt_tokens = tokens.get("prompt_tokens", 0) or 0
            completion_tokens = tokens.get("completion_tokens", 0) or 0

            logger.info(
                f"Generated SQL query in {duration_ms:.2f}ms. Tokens used: {prompt_tokens} prompt / {completion_tokens} completion."
            )

            return final_sql

        # Self-consistency generation
        logger.info("Generating %d SQL candidates using self-consistency...", settings.sql_candidates)

        start_time = time.time()
        payload = self.prompt_builder.build_generation_input(
            schema_text=schema_text,
            question=question,
            conversation_history=conversation_history,
        )
        tasks = [
            self.self_consistency_chain.ainvoke(payload)
            for _ in range(settings.sql_candidates)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        duration_ms = (time.time() - start_time) * 1000

        total_prompt_tokens = 0
        total_completion_tokens = 0
        exceptions = []
        candidates = []
        for res in results:
            if isinstance(res, Exception):
                exceptions.append(f"{type(res).__name__}: {str(res)}")
                logger.error("Error generating SQL candidate: %s", res)
                continue

            tokens = res.response_metadata.get("token_usage", {}) if hasattr(res, "response_metadata") else {}
            total_prompt_tokens += tokens.get("prompt_tokens", 0) or 0
            total_completion_tokens += tokens.get("completion_tokens", 0) or 0

            # Transpile (incl. default LIMIT enforcement) *before* validation below,
            # so the dry-run execution check on each candidate is bounded too -
            # otherwise every one of the N candidates gets fully executed
            # unlimited during voting, and only the single winner gets the
            # LIMIT applied afterwards. transpile() is idempotent (no-op if a
            # LIMIT is already present) so this is safe to call again later.
            candidates.append(self.validator.transpile(self.validator.sanitize_and_extract(res.content)))

        logger.info(
            f"Generated {len(candidates)} SQL candidates using self-consistency in {duration_ms:.2f}ms. Total tokens: {total_prompt_tokens} prompt / {total_completion_tokens} completion."
        )

        if not candidates:
            raise RuntimeError(f"Failed to generate any SQL candidates. Exceptions encountered: {'; '.join(exceptions)}")

        # Validate candidates
        valid_candidates = []
        for sql in candidates:
            # 1. Safety validation
            val = self.validator.validate_safety(sql)
            if not val["valid"]:
                continue

            # 2. Execution validation (dry run)
            is_valid, err = self.validator.validate_execution(sql, db)
            if is_valid:
                valid_candidates.append(sql)
            else:
                logger.debug("Candidate SQL failed execution check: %s. Error: %s", sql, err)

        if not valid_candidates:
            logger.warning("No self-consistency candidates passed execution validation. Falling back to first candidate.")
            final_sql = self.validator.transpile(candidates[0])
            set_cached_sql(question, schema_text, final_sql)
            return final_sql

        votes = {}
        for sql in valid_candidates:
            norm = normalize_sql(sql)
            if norm not in votes:
                votes[norm] = {"sql": sql, "count": 0}
            votes[norm]["count"] += 1

        # Select candidate with highest count
        best_candidate = max(votes.values(), key=lambda x: x["count"])["sql"]
        logger.info("Self-consistency voting selected SQL query with %d votes.", votes[normalize_sql(best_candidate)]["count"])

        final_sql = self.validator.transpile(best_candidate)
        set_cached_sql(question, schema_text, final_sql)
        return final_sql

    async def execute_with_repair(
        self,
        question: str,
        schema_text: str,
        sql: str,
        db: Session,
        max_fix_attempts: int = 2
    ) -> Tuple[List[dict], str, str | None, str | None, List[str]]:
        """
        Execute `sql`, and if it fails, ask the LLM to repair it up to
        max_fix_attempts times. Returns (rows, final_sql, error_message, error_type, suggestions).
        """
        # 1. Check results cache first
        cached_results = get_cached_results(sql)
        if cached_results is not None:
            logger.info("Results cache hit for SQL.")
            return cached_results, sql, None, None, []

        current_sql = sql
        last_error: str | None = None

        for attempt in range(max_fix_attempts + 1):
            try:
                rows = self.sql_executor.execute(current_sql, db)
                # Success! Cache query results before returning
                set_cached_results(current_sql, rows)
                if attempt > 0 and last_error:
                    # Phase 5 (rebuild plan): this succeeded only after a
                    # repair - the identifier named in `last_error` was
                    # wrong and `current_sql` now has the right one. Learn
                    # it for next time. Fire-and-forget: never blocks or
                    # risks the answer that already succeeded.
                    try:
                        from app.services.schema_learning import record_repair_correction
                        await record_repair_correction(self.repair_engine.schema_service, last_error, current_sql)
                    except Exception as learn_err:
                        logger.debug("Schema-learning hook skipped: %s", learn_err)
                return rows, current_sql, None, None, []
            except Exception as execution_error:
                last_error = str(execution_error)
                if attempt >= max_fix_attempts:
                    break

                logger.warning(
                    "SQL execution failed (attempt %d/%d): %s",
                    attempt + 1,
                    max_fix_attempts,
                    last_error,
                )

                fixed_sql = await self.fix_sql(
                    question=question,
                    schema_text=schema_text,
                    failed_sql=current_sql,
                    error=last_error,
                )

                reason = self.unanswerable_reason(fixed_sql)
                if reason:
                    return [], fixed_sql, f"UNANSWERABLE: {reason}", "schema", []

                fixed_validation = self.validator.validate_safety(fixed_sql)
                if not fixed_validation["valid"]:
                    return [], fixed_sql, fixed_validation["reason"], fixed_validation.get("query_type"), []

                current_sql = self.validator.transpile(fixed_sql)

        # If we got here, all attempts failed. Analyze the error.
        error_type, suggestions = self.analyze_db_error(last_error)
        return [], current_sql, last_error, error_type, suggestions

    async def fix_sql(
        self,
        question: str,
        schema_text: str,
        failed_sql: str,
        error: str,
    ) -> str:
        """Ask the LLM to repair a failed SQL query once."""
        return await self.repair_engine.fix_sql(
            question=question,
            schema_text=schema_text,
            failed_sql=failed_sql,
            error=error,
        )

    def analyze_db_error(self, error_msg: str) -> Tuple[str, List[str]]:
        """Analyze database error message and return (error_type, suggestions)."""
        return self.repair_engine.analyze_db_error(error_msg)

    @staticmethod
    def unanswerable_reason(sql: str) -> str | None:
        """Return the reason text if `sql` is the UNANSWERABLE sentinel, else None."""
        return GroundingEngine.unanswerable_reason(sql)

    def extract_sql(self, text: str) -> str:
        """Extract SQL query from LLM response, handling markdown fences."""
        return extract_sql(text)
