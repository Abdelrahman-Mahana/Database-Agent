"""Caching utilities for generated SQL queries and database results."""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional, Tuple

from cachetools import TTLCache
from app.config.settings import settings
from app.database.system_store import system_store
from app.utils.text_processor import normalize_question

logger = logging.getLogger(__name__)

# Layer 1: In-memory TTLCaches for fastest access
_sql_cache = TTLCache(maxsize=10000, ttl=settings.sql_cache_ttl)
_results_cache = TTLCache(maxsize=10000, ttl=settings.results_cache_ttl)
_chart_cache = TTLCache(maxsize=10000, ttl=settings.results_cache_ttl)
_report_cache = TTLCache(maxsize=10000, ttl=settings.report_cache_ttl)


def _get_hash_key(key_str: str) -> str:
    """Generate SHA256 hash of a string to use as cache key."""
    return hashlib.sha256(key_str.encode("utf-8")).hexdigest()


def get_cached_sql(
    question: str,
    schema_text: str,
    database_fingerprint: str = "",
    dialect: str = "",
) -> Tuple[Optional[str], Optional[dict[str, Any]]]:
    norm_q = normalize_question(question)
    raw_key = f"{database_fingerprint}:{dialect}:{norm_q}:{schema_text}"
    cache_key = f"sql:{_get_hash_key(raw_key)}"
    
    val = _sql_cache.get(cache_key)
    if val:
        logger.info("SQL cache hit (In-Memory) for question.")
        if isinstance(val, dict):
            return val.get("sql"), val
        return val, {}
            
    val = system_store.get_cache(cache_key)
    if val:
        logger.info("SQL cache hit (Local DB) for question.")
        data = json.loads(val)
        _sql_cache[cache_key] = data  # Write-through back to local in-memory cache
        if isinstance(data, dict):
            return data.get("sql"), data
        return data, {}
    return None, None


def set_cached_sql(
    question: str,
    schema_text: str,
    sql: str,
    database_fingerprint: str = "",
    dialect: str = "",
    origin_generation_tier: str = "primary",
) -> None:
    norm_q = normalize_question(question)
    raw_key = f"{database_fingerprint}:{dialect}:{norm_q}:{schema_text}"
    cache_key = f"sql:{_get_hash_key(raw_key)}"
    
    entry = {
        "sql": sql,
        "origin_generation_tier": origin_generation_tier,
    }
    
    # L1 Hot Path: In-memory RAM Cache
    _sql_cache[cache_key] = entry

    # L2 Durable Persistence (Safe non-blocking update to SQLite)
    try:
        system_store.set_cache(cache_key, json.dumps(entry), settings.sql_cache_ttl)
    except Exception as e:
        logger.debug("Failed to persist SQL cache to SQLite: %s", e)


def get_cached_report(question: str, sql: str, results_fingerprint: str) -> str | None:
    norm_q = normalize_question(question)
    cache_key = f"report:{_get_hash_key(f'{norm_q}:{sql}:{results_fingerprint}')}"

    # L1 Hot RAM lookup (0ms)
    val = _report_cache.get(cache_key)
    if val:
        logger.info("Report cache hit (In-Memory).")
        return val

    # L2 Cold SQLite lookup
    try:
        val = system_store.get_cache(cache_key)
        if val:
            logger.info("Report cache hit (Local DB).")
            _report_cache[cache_key] = val  # Write-through to L1 RAM
            return val
    except Exception as e:
        logger.debug("Failed to read report cache from SQLite: %s", e)
    return None


def set_cached_report(question: str, sql: str, results_fingerprint: str, report: str) -> None:
    norm_q = normalize_question(question)
    cache_key = f"report:{_get_hash_key(f'{norm_q}:{sql}:{results_fingerprint}')}"

    # L1 Hot RAM write
    _report_cache[cache_key] = report

    # L2 Cold persistence
    try:
        system_store.set_cache(cache_key, report, settings.report_cache_ttl)
    except Exception as e:
        logger.debug("Failed to persist report cache to SQLite: %s", e)


def get_cached_results(
    sql: str,
    database_fingerprint: str = "",
    dialect: str = "",
) -> list[dict[str, Any]] | None:
    raw_key = f"{database_fingerprint}:{dialect}:{sql}"
    cache_key = f"results:{_get_hash_key(raw_key)}"

    # L1 Hot RAM lookup (0ms)
    val = _results_cache.get(cache_key)
    if val:
        logger.info("Results cache hit (In-Memory) for SQL.")
        return val

    # L2 Cold SQLite lookup
    try:
        val = system_store.get_cache(cache_key)
        if val:
            logger.info("Results cache hit (Local DB) for SQL.")
            data = json.loads(val)
            _results_cache[cache_key] = data  # Write-through to L1 RAM
            return data
    except Exception as e:
        logger.debug("Failed to read results cache from SQLite: %s", e)
    return None


def set_cached_results(
    sql: str,
    results: list[dict[str, Any]],
    database_fingerprint: str = "",
    dialect: str = "",
) -> None:
    raw_key = f"{database_fingerprint}:{dialect}:{sql}"
    cache_key = f"results:{_get_hash_key(raw_key)}"

    # L1 Hot RAM write
    _results_cache[cache_key] = results

    # L2 Cold persistence
    try:
        system_store.set_cache(cache_key, json.dumps(results, default=str), settings.results_cache_ttl)
    except Exception as e:
        logger.debug("Failed to persist results cache to SQLite: %s", e)


def get_cached_chart(sql: str) -> dict[str, Any] | None:
    cache_key = f"chart:{_get_hash_key(sql)}"

    # L1 Hot RAM lookup (0ms)
    val = _chart_cache.get(cache_key)
    if val:
        logger.info("Chart cache hit (In-Memory) for SQL.")
        return val

    # L2 Cold SQLite lookup
    try:
        val = system_store.get_cache(cache_key)
        if val:
            logger.info("Chart cache hit (Local DB) for SQL.")
            data = json.loads(val)
            _chart_cache[cache_key] = data  # Write-through to L1 RAM
            return data
    except Exception as e:
        logger.debug("Failed to read chart cache from SQLite: %s", e)
    return None


def set_cached_chart(sql: str, chart: dict[str, Any]) -> None:
    cache_key = f"chart:{_get_hash_key(sql)}"

    # L1 Hot RAM write
    _chart_cache[cache_key] = chart

    # L2 Cold persistence
    try:
        system_store.set_cache(cache_key, json.dumps(chart, default=str), settings.results_cache_ttl)
    except Exception as e:
        logger.debug("Failed to persist chart cache to SQLite: %s", e)


def clear_all_caches() -> None:
    _sql_cache.clear()
    _results_cache.clear()
    _chart_cache.clear()
    _report_cache.clear()
    system_store.clear_cache()
    logger.info("All in-memory and local DB caches cleared.")
