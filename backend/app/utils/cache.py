"""Caching utilities for generated SQL queries, reports, charts, and query results.

Features:
1. Hard row count and byte size budgets on cached result payloads.
2. Volatility detection with reduced TTL or bypass for mutable/streaming data.
3. Data freshness / version tagging for mutation-sensitive invalidation.
4. Three-tier caching hierarchy:
   - L1: In-RAM TTLCache (0ms)
   - L2: Cross-Worker Distributed Redis cache (sub-millisecond)
   - L3: Durable SystemStore (PostgreSQL / SQLite)
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Optional, Tuple

from cachetools import TTLCache
from app.core.config.settings import settings
from app.services.database.system_store import system_store
from app.services.database.redis_store import get_redis_coordinator
from app.utils.helpers import normalize_question

logger = logging.getLogger(__name__)

# Layer 1: In-memory TTLCaches for fastest access (bounded to prevent RAM bloating)
_sql_cache = TTLCache(maxsize=10000, ttl=settings.sql_cache_ttl)
_results_cache = TTLCache(maxsize=1000, ttl=settings.results_cache_ttl)
_chart_cache = TTLCache(maxsize=5000, ttl=settings.results_cache_ttl)
_report_cache = TTLCache(maxsize=5000, ttl=settings.report_cache_ttl)

# Non-deterministic functions that produce varying results on every execution
_NON_DETERMINISTIC_SQL_FUNCS = {
    "now()", "current_timestamp", "current_date", "current_time",
    "random()", "rand()", "uuid()", "newid()", "gen_random_uuid()",
    "sysdate", "clock_timestamp()", "timeofday()"
}


def _get_hash_key(key_str: str) -> str:
    """Generate SHA256 hash of a string to use as cache key."""
    return hashlib.sha256(key_str.encode("utf-8")).hexdigest()


def is_volatile_query(sql: str) -> bool:
    """
    Detect whether a query references non-deterministic functions or volatile table patterns.
    """
    sql_lower = sql.lower()

    # Check non-deterministic SQL functions
    for func in _NON_DETERMINISTIC_SQL_FUNCS:
        if func in sql_lower:
            return True

    # Check volatile table names
    patterns = getattr(settings, "volatile_table_patterns", ["logs", "events", "transactions", "audit", "stream"])
    tokens = set(re.findall(r'[a-zA-Z0-9_]+', sql_lower))
    for pat in patterns:
        if pat.lower() in tokens or any(t.startswith(f"{pat}_") or t.endswith(f"_{pat}") for t in tokens):
            return True

    return False


def _build_sql_cache_key(
    question: str,
    schema_text: str = "",
    database_fingerprint: str = "",
    dialect: str = "",
    schema_version: str = "",
) -> str:
    norm_q = normalize_question(question)
    version_tag = schema_version or (_get_hash_key(schema_text) if schema_text else "")
    raw_key = f"{database_fingerprint}:{dialect}:{version_tag}:{norm_q}"
    return f"sql:{_get_hash_key(raw_key)}"


def _build_results_cache_key(
    sql: str,
    database_fingerprint: str = "",
    dialect: str = "",
    data_version: str = "",
    schema_version: str = "",
) -> str:
    raw_key = f"{database_fingerprint}:{dialect}:{schema_version}:{data_version}:{sql.strip()}"
    return f"results:{_get_hash_key(raw_key)}"


# -----------------------------------------------------------------------------
# 1. SQL Query Cache
# -----------------------------------------------------------------------------

def get_cached_sql(
    question: str,
    schema_text: str = "",
    database_fingerprint: str = "",
    dialect: str = "",
    schema_version: str = "",
) -> Tuple[Optional[str], Optional[dict[str, Any]]]:
    cache_key = _build_sql_cache_key(
        question=question,
        schema_text=schema_text,
        database_fingerprint=database_fingerprint,
        dialect=dialect,
        schema_version=schema_version,
    )

    def _clean_sql(entry: Any) -> tuple[Optional[str], dict]:
        if not entry:
            return None, None
        sql_val = entry.get("sql") if isinstance(entry, dict) else str(entry)
        if not sql_val or "UNANSWERABLE" in sql_val.upper() or "SELECT 'UNANSWERABLE" in sql_val.upper():
            return None, None
        return sql_val, (entry if isinstance(entry, dict) else {})

    # L1: Hot In-RAM TTLCache
    val = _sql_cache.get(cache_key)
    if val:
        sql, meta = _clean_sql(val)
        if sql:
            logger.info("SQL cache hit (In-Memory) for question.")
            return sql, meta
        _sql_cache.pop(cache_key, None)

    # L2: Cross-Worker Distributed Redis
    redis_coord = get_redis_coordinator()
    if redis_coord.is_available():
        r_val = redis_coord.get(cache_key)
        if r_val:
            try:
                data = json.loads(r_val)
                sql, meta = _clean_sql(data)
                if sql:
                    logger.info("SQL cache hit (Redis) for question.")
                    _sql_cache[cache_key] = data
                    return sql, meta
            except Exception:
                pass

    # L3: Durable SystemStore
    val = system_store.get_cache(cache_key)
    if val:
        try:
            data = json.loads(val)
            sql, meta = _clean_sql(data)
            if sql:
                logger.info("SQL cache hit (Durable Store) for question.")
                _sql_cache[cache_key] = data
                return sql, meta
        except Exception:
            pass
    return None, None


def set_cached_sql(
    question: str,
    schema_text: str = "",
    sql: str = "",
    database_fingerprint: str = "",
    dialect: str = "",
    origin_generation_tier: str = "primary",
    schema_version: str = "",
) -> None:
    if not sql or "UNANSWERABLE" in sql.upper() or "SELECT 'UNANSWERABLE" in sql.upper():
        return

    cache_key = _build_sql_cache_key(
        question=question,
        schema_text=schema_text,
        database_fingerprint=database_fingerprint,
        dialect=dialect,
        schema_version=schema_version,
    )

    entry = {
        "sql": sql,
        "origin_generation_tier": origin_generation_tier,
    }
    serialized = json.dumps(entry)

    # L1: Hot Path RAM Cache
    _sql_cache[cache_key] = entry

    # L2: Distributed Redis
    redis_coord = get_redis_coordinator()
    if redis_coord.is_available():
        redis_coord.set(cache_key, serialized, ttl_seconds=settings.sql_cache_ttl)

    # L3: Durable Persistence
    try:
        system_store.set_cache(cache_key, serialized, settings.sql_cache_ttl)
    except Exception as e:
        logger.debug("Failed to persist SQL cache: %s", e)


def invalidate_cached_sql(
    question: str,
    schema_text: str = "",
    database_fingerprint: str = "",
    dialect: str = "",
    schema_version: str = "",
) -> None:
    """Evict cached SQL query across all cache layers."""
    cache_key = _build_sql_cache_key(
        question=question,
        schema_text=schema_text,
        database_fingerprint=database_fingerprint,
        dialect=dialect,
        schema_version=schema_version,
    )
    _sql_cache.pop(cache_key, None)
    redis_coord = get_redis_coordinator()
    if redis_coord.is_available():
        try:
            redis_coord.delete(cache_key)
        except Exception:
            pass
    try:
        if hasattr(system_store, "delete_cache"):
            system_store.delete_cache(cache_key)
    except Exception:
        pass


# -----------------------------------------------------------------------------
# 2. Query Results Cache (Bounded, Volatility-Aware, Freshness-Keyed)
# -----------------------------------------------------------------------------

def get_cached_results(
    sql: str,
    database_fingerprint: str = "",
    dialect: str = "",
    data_version: str = "",
    schema_version: str = "",
) -> list[dict[str, Any]] | None:
    """Fetch cached query results if results caching is enabled and entry has not expired."""
    if not getattr(settings, "enable_results_cache", True):
        return None

    cache_key = _build_results_cache_key(
        sql=sql,
        database_fingerprint=database_fingerprint,
        dialect=dialect,
        data_version=data_version,
        schema_version=schema_version,
    )

    # L1: Hot RAM lookup (0ms)
    val = _results_cache.get(cache_key)
    if val is not None:
        logger.info("Results cache hit (In-Memory) for SQL.")
        return val

    # L2: Distributed Redis lookup
    redis_coord = get_redis_coordinator()
    if redis_coord.is_available():
        r_val = redis_coord.get(cache_key)
        if r_val:
            try:
                logger.info("Results cache hit (Redis) for SQL.")
                data = json.loads(r_val)
                _results_cache[cache_key] = data
                return data
            except Exception:
                pass

    # L3: Cold SystemStore lookup
    try:
        stored = system_store.get_cache(cache_key)
        if stored:
            logger.info("Results cache hit (Durable Store) for SQL.")
            data = json.loads(stored)
            _results_cache[cache_key] = data  # Write-through to L1 RAM
            return data
    except Exception as e:
        logger.debug("Failed to read results cache: %s", e)
    return None


def set_cached_results(
    sql: str,
    results: list[dict[str, Any]],
    database_fingerprint: str = "",
    dialect: str = "",
    data_version: str = "",
    schema_version: str = "",
) -> None:
    """
    Store query results in cache subject to strict row budget, payload byte budget, and volatility TTL.
    """
    if not getattr(settings, "enable_results_cache", True):
        return

    # 1. Enforce row budget
    max_rows = getattr(settings, "cache_results_max_rows", 500)
    if len(results) > max_rows:
        logger.debug("Skipping results cache: row count (%d) exceeds max budget (%d)", len(results), max_rows)
        return

    # 2. Enforce byte payload budget
    try:
        serialized = json.dumps(results, default=str)
    except Exception as ser_err:
        logger.debug("Failed to serialize results for caching: %s", ser_err)
        return

    max_bytes = getattr(settings, "cache_results_max_bytes", 512_000)
    if len(serialized.encode("utf-8")) > max_bytes:
        logger.debug("Skipping results cache: payload bytes (%d) exceeds max budget (%d)", len(serialized), max_bytes)
        return

    # 3. Determine TTL based on query volatility
    ttl = settings.results_cache_ttl
    if is_volatile_query(sql):
        ttl = getattr(settings, "results_cache_volatile_ttl", 30)

    if ttl <= 0:
        return

    cache_key = _build_results_cache_key(
        sql=sql,
        database_fingerprint=database_fingerprint,
        dialect=dialect,
        data_version=data_version,
        schema_version=schema_version,
    )

    # L1: Hot RAM write
    _results_cache[cache_key] = results

    # L2: Distributed Redis write
    redis_coord = get_redis_coordinator()
    if redis_coord.is_available():
        redis_coord.set(cache_key, serialized, ttl_seconds=ttl)

    # L3: Durable persistence
    try:
        system_store.set_cache(cache_key, serialized, ttl)
    except Exception as e:
        logger.debug("Failed to persist results cache: %s", e)
    except Exception as e:
        logger.debug("Failed to persist results cache: %s", e)


# -----------------------------------------------------------------------------
# 3. Analyst Report and Chart Caches
# -----------------------------------------------------------------------------

def build_report_cache_key(
    question: str,
    sql: str,
    results_fingerprint: str,
    *,
    report_prompt_version: str,
    model_id: str,
    locale: str,
    tone: str,
    user_context: str,
) -> str:
    """Build a versioned report identity across all cache tiers.

    Result cache validity is data-oriented; report cache validity is also
    presentation-oriented.  Keep prompt/model/user preferences in this key so
    changes to any of them cannot serve a report produced under old behavior.
    """
    payload = {
        "question": normalize_question(question),
        "sql": sql.strip(),
        "result_fingerprint": results_fingerprint,
        "report_prompt_version": report_prompt_version,
        "model_id": model_id,
        "locale": locale,
        "tone": tone,
        "user_context": user_context,
    }
    return f"report:v2:{_get_hash_key(json.dumps(payload, sort_keys=True, separators=(',', ':')))}"


def get_cached_report(
    question: str,
    sql: str,
    results_fingerprint: str,
    *,
    report_prompt_version: str = "legacy-v1",
    model_id: str = "unknown",
    locale: str = "auto",
    tone: str = "executive",
    user_context: str = "default_user",
) -> str | None:
    cache_key = build_report_cache_key(
        question, sql, results_fingerprint,
        report_prompt_version=report_prompt_version,
        model_id=model_id,
        locale=locale,
        tone=tone,
        user_context=user_context,
    )

    val = _report_cache.get(cache_key)
    if val:
        logger.info("Report cache hit (In-Memory).")
        return val

    redis_coord = get_redis_coordinator()
    if redis_coord.is_available():
        r_val = redis_coord.get(cache_key)
        if r_val:
            logger.info("Report cache hit (Redis).")
            _report_cache[cache_key] = r_val
            return r_val

    try:
        val = system_store.get_cache(cache_key)
        if val:
            logger.info("Report cache hit (Durable Store).")
            _report_cache[cache_key] = val
            return val
    except Exception as e:
        logger.debug("Failed to read report cache: %s", e)
    return None


def set_cached_report(
    question: str,
    sql: str,
    results_fingerprint: str,
    report: str,
    *,
    report_prompt_version: str = "legacy-v1",
    model_id: str = "unknown",
    locale: str = "auto",
    tone: str = "executive",
    user_context: str = "default_user",
) -> None:
    cache_key = build_report_cache_key(
        question, sql, results_fingerprint,
        report_prompt_version=report_prompt_version,
        model_id=model_id,
        locale=locale,
        tone=tone,
        user_context=user_context,
    )

    _report_cache[cache_key] = report

    redis_coord = get_redis_coordinator()
    if redis_coord.is_available():
        redis_coord.set(cache_key, report, ttl_seconds=settings.report_cache_ttl)

    try:
        system_store.set_cache(cache_key, report, settings.report_cache_ttl)
    except Exception as e:
        logger.debug("Failed to persist report cache: %s", e)


def get_cached_chart(sql: str) -> dict[str, Any] | None:
    cache_key = f"chart:{_get_hash_key(sql)}"

    val = _chart_cache.get(cache_key)
    if val:
        logger.info("Chart cache hit (In-Memory) for SQL.")
        return val

    redis_coord = get_redis_coordinator()
    if redis_coord.is_available():
        r_val = redis_coord.get(cache_key)
        if r_val:
            try:
                data = json.loads(r_val)
                _chart_cache[cache_key] = data
                return data
            except Exception:
                pass

    try:
        val = system_store.get_cache(cache_key)
        if val:
            logger.info("Chart cache hit (Durable Store) for SQL.")
            data = json.loads(val)
            _chart_cache[cache_key] = data
            return data
    except Exception as e:
        logger.debug("Failed to read chart cache: %s", e)
    return None


def set_cached_chart(sql: str, chart: dict[str, Any]) -> None:
    cache_key = f"chart:{_get_hash_key(sql)}"
    serialized = json.dumps(chart, default=str)

    _chart_cache[cache_key] = chart

    redis_coord = get_redis_coordinator()
    if redis_coord.is_available():
        redis_coord.set(cache_key, serialized, ttl_seconds=settings.results_cache_ttl)

    try:
        system_store.set_cache(cache_key, serialized, settings.results_cache_ttl)
    except Exception as e:
        logger.debug("Failed to persist chart cache: %s", e)


def clear_all_caches() -> None:
    """Clear all L1 in-memory caches, L2 Redis caches, and L3 persistent cache."""
    _sql_cache.clear()
    _results_cache.clear()
    _chart_cache.clear()
    _report_cache.clear()
    system_store.clear_cache()
    logger.info("All in-memory, Redis, and durable caches cleared.")
