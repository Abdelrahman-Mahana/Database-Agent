"""Module for orchestrating SQL generation, validation, execution, and repair."""
import asyncio
import logging
import time
from typing import Any, Callable, List, Tuple, Optional

from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.services.sql_service import SchemaService, SQLExecutor
from app.utils.cache import get_cached_sql, set_cached_sql, get_cached_results, set_cached_results
from app.utils.helpers import extract_sql, normalize_sql, filter_schema_by_query
from app.services.sql import (
    SQLPromptBuilder,
    AnswerabilityChecker,
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
        self.answerability_checker = AnswerabilityChecker()
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
        query_understanding: Optional[Any] = None,
    ) -> str:
        """Generate and normalize a SQL query for the user's question using LangChain and self-consistency voting."""
        # 1. Check generated SQL cache first
        fp = self.schema_service._get_db_fingerprint()
        dialect_name = getattr(self.schema_service, "get_database_type", lambda: "sql")().lower()
        schema_ver = getattr(self.schema_service, "get_semantic_schema_version", lambda: fp)()

        cached_sql, cache_meta = get_cached_sql(
            question,
            schema_text,
            database_fingerprint=fp,
            dialect=dialect_name,
            schema_version=schema_ver,
        )
        if cached_sql:
            origin_tier = (cache_meta or {}).get("origin_generation_tier", "primary")
            self.last_generation_meta = {
                "sql_generation_tier": origin_tier,
                "sql_cache_hit": True,
            }
            return cached_sql

        use_voting = settings.enable_self_consistency if use_self_consistency is None else use_self_consistency
        gen_tier = (
            "self_consistency"
            if (use_voting and settings.sql_candidates > 1)
            else ("fast" if (use_fast_model and self.fast_generation_chain is not None) else "primary")
        )
        self.last_generation_meta = {
            "sql_generation_tier": gen_tier,
            "sql_cache_hit": False,
        }

        db_ident = fp
        try:
            db_ctx = self.schema_service.get_database_context()
            if db_ctx and db_ctx.database_name:
                db_ident = db_ctx.database_name
        except Exception:
            pass
        if not db_ident or db_ident == fp:
            db_ident = getattr(self.schema_service, "database_name", "") or settings.database_url or fp

        if not use_voting or settings.sql_candidates <= 1:
            # Single candidate generation
            start_time = time.time()
            payload = self.prompt_builder.build_generation_input(
                schema_text=schema_text,
                question=question,
                conversation_history=conversation_history,
                query_understanding=query_understanding,
                dialect=dialect_name,
                db_identifier=db_ident,
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
            query_understanding=query_understanding,
            dialect=dialect_name,
            db_identifier=db_ident,
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

            candidates.append(self.validator.transpile(self.validator.sanitize_and_extract(res.content)))

        logger.info(
            f"Generated {len(candidates)} SQL candidates using self-consistency in {duration_ms:.2f}ms. Total tokens: {total_prompt_tokens} prompt / {total_completion_tokens} completion."
        )

        if not candidates:
            if self.fast_generation_chain is not None:
                logger.warning("All primary candidates failed (e.g. RateLimit). Falling back to fast model...")
                try:
                    res = await self.fast_generation_chain.ainvoke(payload)
                    raw_sql = self.validator.sanitize_and_extract(res.content)
                    final_sql = self.validator.transpile(raw_sql)
                    return final_sql
                except Exception as fast_err:
                    logger.error("Fast model fallback also failed: %s", fast_err)
            raise RuntimeError(f"Failed to generate any SQL candidates. Exceptions encountered: {'; '.join(exceptions)}")

        # Validate candidates via AST checks & dialect-aware EXPLAIN (zero live query execution)
        valid_candidates = []
        raw_schema = None
        catalog = None
        try:
            db_ctx = self.schema_service.get_database_context()
            raw_schema = db_ctx.schema if db_ctx else None
            catalog = db_ctx.catalog if db_ctx else None
        except Exception:
            pass

        for sql in candidates:
            # 1. AST Safety & structure validation
            val = self.validator.validate_safety(sql)
            if not val.get("valid", False):
                logger.debug("Candidate SQL failed safety validation: %s (%s)", sql, val.get("reason"))
                continue

            # 2. Identifier grounding & join validation (AST vs catalog/schema)
            if raw_schema or catalog:
                id_valid, id_warn = self.validator.verify_sql_identifiers(
                    sql, catalog=catalog, raw_schema=raw_schema,
                )
                if not id_valid:
                    logger.debug("Candidate SQL failed identifier grounding: %s (%s)", sql, id_warn)
                    continue

                join_valid, join_warn = self.validator.verify_sql_joins(sql, catalog=catalog)
                if not join_valid:
                    logger.debug("Candidate SQL failed join validation: %s (%s)", sql, join_warn)
                    continue

                if query_understanding:
                    meaning_valid, meaning_warn = self.validator.verify_query_spec_alignment(
                        sql, query_spec=query_understanding, catalog=catalog, raw_schema=raw_schema
                    )
                    if not meaning_valid:
                        logger.debug("Candidate SQL failed semantic grain or fan-out validation: %s (%s)", sql, meaning_warn)
                        continue

            # 3. Dialect-aware plan validation (EXPLAIN) - zero live data execution
            is_valid, err = self.validator.validate_execution(sql, db)
            if is_valid:
                valid_candidates.append(sql)
            else:
                logger.debug("Candidate SQL failed plan check: %s. Error: %s", sql, err)

        if not valid_candidates:
            if self.fast_generation_chain is not None:
                logger.warning(
                    "No self-consistency candidates passed validation. Falling back to fast model..."
                )
                try:
                    res = await self.fast_generation_chain.ainvoke(payload)
                    raw_sql = self.validator.sanitize_and_extract(res.content)
                    final_sql = self.validator.transpile(raw_sql)
                    return final_sql
                except Exception as fast_err:
                    logger.error("Fast model fallback also failed: %s", fast_err)
            raise RuntimeError(
                "No self-consistency candidates passed SQL safety, grounding, join, or plan validation."
            )

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
        return final_sql

    async def execute_with_repair(
        self,
        question: str,
        schema_text: str,
        sql: str,
        db: Session,
        max_fix_attempts: int = 2,
        initial_tier: str | None = None,
        sql_cache_hit: bool | None = None,
        pre_execution_gate: Callable[[str], Any] | None = None,
        query_understanding: Optional[Any] = None,
        conversation_history: str = "",
        db_identifier: str = "",
    ) -> Tuple[List[dict], str, str | None, str | None, List[str]]:
        """
        Execute `sql`, and if it fails, ask the LLM to repair it up to
        max_fix_attempts times with full semantic contract fidelity.
        Returns (rows, final_sql, error_message, error_type, suggestions).
        """
        fp = self.schema_service._get_db_fingerprint()
        freshness_token = getattr(self.schema_service, "get_data_freshness_token", lambda: "")()
        dialect_name = getattr(self.schema_service, "get_database_type", lambda: "sql")().lower()
        schema_ver = getattr(self.schema_service, "get_semantic_schema_version", lambda: fp)()

        gen_meta = getattr(self, "last_generation_meta", {})
        gen_tier = initial_tier or gen_meta.get("sql_generation_tier", "primary")
        is_cache_hit = sql_cache_hit if sql_cache_hit is not None else gen_meta.get("sql_cache_hit", False)

        db_ident = db_identifier or fp
        try:
            db_ctx = self.schema_service.get_database_context()
            if db_ctx and db_ctx.database_name:
                db_ident = db_ctx.database_name
        except Exception:
            pass
        if not db_ident or db_ident == fp:
            db_ident = getattr(self.schema_service, "database_name", "") or settings.database_url or fp

        # Every SQL provenance (including a cache hit and each repair) must
        # clear the caller's canonical control gate before it can be used.
        def blocked_by_gate(candidate_sql: str) -> tuple[str, str] | None:
            if pre_execution_gate is None:
                return None
            gate_result = pre_execution_gate(candidate_sql)
            if not gate_result.allowed:
                return gate_result.reason or "SQL control gate rejected the query.", gate_result.error_type or "sql_control_gate"
            return None

        initial_block = blocked_by_gate(sql)

        # 1. Check results cache first
        cached_results = get_cached_results(
            sql,
            database_fingerprint=fp,
            dialect=dialect_name,
            data_version=freshness_token,
            schema_version=schema_ver,
        )
        if cached_results is not None and not initial_block:
            logger.info("Results cache hit for SQL.")
            self.last_execution_meta = {
                "sql_generation_tier": gen_tier,
                "sql_final_tier": gen_tier,
                "sql_repair_attempts": 0,
                "sql_repair_success": True,
                "sql_cache_hit": is_cache_hit,
            }
            return cached_results, sql, None, None, []

        current_sql = sql
        last_error: str | None = initial_block[0] if initial_block else None
        last_error_type: str | None = initial_block[1] if initial_block else None

        for attempt in range(max_fix_attempts + 1):
            # Semantic gate failures are repairable SQL defects, just like
            # syntax/schema execution failures. Repair before touching data.
            gate_block = blocked_by_gate(current_sql)
            if gate_block:
                last_error, last_error_type = gate_block
                if attempt >= max_fix_attempts:
                    break
                fixed_sql = await self.fix_sql(
                    question=question,
                    schema_text=schema_text,
                    failed_sql=current_sql,
                    error=last_error,
                    dialect=dialect_name,
                    query_understanding=query_understanding,
                    conversation_history=conversation_history,
                    db_identifier=db_ident,
                )
                reason = self.unanswerable_reason(fixed_sql)
                if reason:
                    self.last_execution_meta = {
                        "sql_generation_tier": gen_tier,
                        "sql_final_tier": f"{gen_tier}_failed",
                        "sql_repair_attempts": attempt + 1,
                        "sql_repair_success": False,
                        "sql_cache_hit": is_cache_hit,
                    }
                    return [], fixed_sql, f"UNANSWERABLE: {reason}", "schema", []

                fixed_validation = self.validator.validate_safety(fixed_sql)
                if not fixed_validation["valid"]:
                    last_error = fixed_validation["reason"]
                    last_error_type = fixed_validation.get("query_type")
                    if attempt >= max_fix_attempts:
                        break
                    current_sql = fixed_sql
                    continue

                current_sql = self.validator.transpile(fixed_sql)
                continue

            try:
                rows = self.sql_executor.execute(current_sql, db)
                # Success! Now that query is approved and executed without errors,
                # commit to SQL cache and results cache with semantic schema version.
                final_tier = gen_tier if attempt == 0 else f"{gen_tier}_repair"
                set_cached_sql(
                    question=question,
                    schema_text=schema_text,
                    sql=current_sql,
                    database_fingerprint=fp,
                    dialect=dialect_name,
                    origin_generation_tier=final_tier,
                    schema_version=schema_ver,
                )
                set_cached_results(
                    current_sql,
                    rows,
                    database_fingerprint=fp,
                    dialect=dialect_name,
                    data_version=freshness_token,
                    schema_version=schema_ver,
                )
                self.last_execution_meta = {
                    "sql_generation_tier": gen_tier,
                    "sql_final_tier": final_tier,
                    "sql_repair_attempts": attempt,
                    "sql_repair_success": True,
                    "sql_cache_hit": is_cache_hit,
                }
                if attempt > 0 and last_error:
                    try:
                        from app.services.schema_learning import record_repair_correction
                        await record_repair_correction(self.repair_engine.schema_service, last_error, current_sql)
                    except Exception as learn_err:
                        logger.debug("Schema-learning hook skipped: %s", learn_err)
                return rows, current_sql, None, None, []
            except Exception as execution_error:
                last_error = str(execution_error)
                
                # Invalidate stale cache entry if cached query failed execution
                if is_cache_hit:
                    try:
                        invalidate_cached_sql(
                            question=question,
                            schema_text=schema_text,
                            database_fingerprint=fp,
                            dialect=dialect_name,
                            schema_version=schema_ver,
                        )
                    except Exception:
                        pass

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
                    dialect=dialect_name,
                    query_understanding=query_understanding,
                    conversation_history=conversation_history,
                    db_identifier=db_ident,
                )

                reason = self.unanswerable_reason(fixed_sql)
                if reason:
                    self.last_execution_meta = {
                        "sql_generation_tier": gen_tier,
                        "sql_final_tier": f"{gen_tier}_failed",
                        "sql_repair_attempts": attempt + 1,
                        "sql_repair_success": False,
                        "sql_cache_hit": is_cache_hit,
                    }
                    return [], fixed_sql, f"UNANSWERABLE: {reason}", "schema", []

                fixed_validation = self.validator.validate_safety(fixed_sql)
                if not fixed_validation["valid"]:
                    self.last_execution_meta = {
                        "sql_generation_tier": gen_tier,
                        "sql_final_tier": f"{gen_tier}_failed",
                        "sql_repair_attempts": attempt + 1,
                        "sql_repair_success": False,
                        "sql_cache_hit": is_cache_hit,
                    }
                    return [], fixed_sql, fixed_validation["reason"], fixed_validation.get("query_type"), []

                current_sql = self.validator.transpile(fixed_sql)

        # If we got here, all attempts failed. Analyze the error.
        error_type, suggestions = self.analyze_db_error(last_error or "SQL execution failed")
        error_type = last_error_type or error_type
        self.last_execution_meta = {
            "sql_generation_tier": gen_tier,
            "sql_final_tier": f"{gen_tier}_failed",
            "sql_repair_attempts": max_fix_attempts,
            "sql_repair_success": False,
            "sql_cache_hit": is_cache_hit,
        }
        return [], current_sql, last_error, error_type, suggestions


    async def fix_sql(
        self,
        question: str,
        schema_text: str,
        failed_sql: str,
        error: str,
        dialect: str = "sqlite",
        query_understanding: Optional[Any] = None,
        conversation_history: str = "",
        db_identifier: str = "",
    ) -> str:
        """Ask the LLM to repair a failed SQL query once with full semantic constraints."""
        return await self.repair_engine.fix_sql(
            question=question,
            schema_text=schema_text,
            failed_sql=failed_sql,
            error=error,
            dialect=dialect,
            query_understanding=query_understanding,
            conversation_history=conversation_history,
            db_identifier=db_identifier,
        )

    def analyze_db_error(self, error_msg: str) -> Tuple[str, List[str]]:
        """Analyze database error message and return (error_type, suggestions)."""
        return self.repair_engine.analyze_db_error(error_msg)

    @staticmethod
    def unanswerable_reason(sql: str) -> str | None:
        """Return the reason text if `sql` is the UNANSWERABLE sentinel, else None."""
        return AnswerabilityChecker.unanswerable_reason(sql)

    def extract_sql(self, text: str) -> str:
        """Extract SQL query from LLM response, handling markdown fences."""
        return extract_sql(text)
