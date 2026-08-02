"""Caching utilities for generated SQL queries and database results."""
import hashlib
import json
import logging
import re
from typing import Any
from cachetools import TTLCache
from app.core.config import settings

logger = logging.getLogger(__name__)

# Initialize local in-memory TTLCaches
# sql_cache: Question/schema -> Generated SQL
_sql_cache = TTLCache(maxsize=100, ttl=settings.sql_cache_ttl)
# results_cache: SQL -> Query results (list of dicts)
_results_cache = TTLCache(maxsize=100, ttl=settings.results_cache_ttl)
# chart_cache: SQL -> Chart suggestion (dict)
_chart_cache = TTLCache(maxsize=100, ttl=settings.results_cache_ttl)
# report_cache: (question, sql, results-fingerprint) -> generated report text (Phase 6)
_report_cache = TTLCache(maxsize=200, ttl=settings.report_cache_ttl)

# Setup Redis client if REDIS_URL is provided
_redis_client = None
if settings.redis_url:
    try:
        import redis
        _redis_client = redis.from_url(settings.redis_url)
        logger.info("Redis cache client initialized successfully.")
    except ImportError:
        logger.warning("redis-py package is not installed. Falling back to TTLCache.")
    except Exception as e:
        logger.warning("Failed to connect to Redis at %s: %s. Falling back to TTLCache.", settings.redis_url, e)


def _get_hash_key(key_str: str) -> str:
    """Generate SHA256 hash of a string to use as cache key."""
    return hashlib.sha256(key_str.encode("utf-8")).hexdigest()


from app.utils.text_processor import normalize_question



def get_cached_sql(question: str, schema_text: str) -> str | None:
    """Retrieve cached SQL query for a given question and schema."""
    norm_q = normalize_question(question)
    cache_key = f"sql:{_get_hash_key(f'{norm_q}:{schema_text}')}"
    
    if _redis_client:
        try:
            val = _redis_client.get(cache_key)
            if val:
                logger.info("SQL cache hit (Redis) for question.")
                return val.decode("utf-8")
        except Exception as e:
            logger.warning("Redis read error in get_cached_sql: %s", e)
            
    # Fallback to local cache
    val = _sql_cache.get(cache_key)
    if val:
        logger.info("SQL cache hit (In-Memory) for question.")
        return val
    return None


def set_cached_sql(question: str, schema_text: str, sql: str) -> None:
    """Store generated SQL query in cache."""
    norm_q = normalize_question(question)
    cache_key = f"sql:{_get_hash_key(f'{norm_q}:{schema_text}')}"
    
    if _redis_client:
        try:
            # Save to Redis with configured TTL
            _redis_client.setex(cache_key, settings.sql_cache_ttl, sql)
            return
        except Exception as e:
            logger.warning("Redis write error in set_cached_sql: %s", e)
            
    _sql_cache[cache_key] = sql


def get_cached_report(question: str, sql: str, results_fingerprint: str) -> str | None:
    """Retrieve a cached report for an identical (question, sql, results) combination.

    Phase 6: repeated dashboard-style questions (same SQL, same underlying
    data since the last write) currently re-run the full report LLM call
    (plus the verification pass for complex questions) every single time.
    Caching by a fingerprint of the actual returned rows — not just the SQL
    text — means a genuinely new answer is generated the moment the
    underlying data changes, while an identical repeat costs nothing.
    """
    norm_q = normalize_question(question)
    cache_key = f"report:{_get_hash_key(f'{norm_q}:{sql}:{results_fingerprint}')}"

    if _redis_client:
        try:
            val = _redis_client.get(cache_key)
            if val:
                logger.info("Report cache hit (Redis).")
                return val.decode("utf-8")
        except Exception as e:
            logger.warning("Redis read error in get_cached_report: %s", e)

    val = _report_cache.get(cache_key)
    if val:
        logger.info("Report cache hit (In-Memory).")
        return val
    return None


def set_cached_report(question: str, sql: str, results_fingerprint: str, report: str) -> None:
    """Store a generated report under its (question, sql, results) fingerprint."""
    norm_q = normalize_question(question)
    cache_key = f"report:{_get_hash_key(f'{norm_q}:{sql}:{results_fingerprint}')}"

    if _redis_client:
        try:
            _redis_client.setex(cache_key, settings.report_cache_ttl, report)
            return
        except Exception as e:
            logger.warning("Redis write error in set_cached_report: %s", e)

    _report_cache[cache_key] = report


def get_cached_results(sql: str) -> list[dict[str, Any]] | None:
    """Retrieve cached database query results for a given SQL query."""
    cache_key = f"results:{_get_hash_key(sql)}"
    
    if _redis_client:
        try:
            val = _redis_client.get(cache_key)
            if val:
                logger.info("Results cache hit (Redis) for SQL.")
                return json.loads(val.decode("utf-8"))
        except Exception as e:
            logger.warning("Redis read error in get_cached_results: %s", e)
            
    # Fallback to local cache
    val = _results_cache.get(cache_key)
    if val:
        logger.info("Results cache hit (In-Memory) for SQL.")
        return val
    return None


def set_cached_results(sql: str, results: list[dict[str, Any]]) -> None:
    """Store database query results in cache."""
    cache_key = f"results:{_get_hash_key(sql)}"
    
    if _redis_client:
        try:
            # Serialize and save to Redis with configured TTL
            serialized = json.dumps(results, default=str)
            _redis_client.setex(cache_key, settings.results_cache_ttl, serialized)
            return
        except Exception as e:
            logger.warning("Redis write error in set_cached_results: %s", e)
            
    _results_cache[cache_key] = results


def get_cached_chart(sql: str) -> dict[str, Any] | None:
    """Retrieve cached chart suggestion for a given SQL query."""
    cache_key = f"chart:{_get_hash_key(sql)}"
    
    if _redis_client:
        try:
            val = _redis_client.get(cache_key)
            if val:
                logger.info("Chart cache hit (Redis) for SQL.")
                return json.loads(val.decode("utf-8"))
        except Exception as e:
            logger.warning("Redis read error in get_cached_chart: %s", e)
            
    # Fallback to local cache
    val = _chart_cache.get(cache_key)
    if val:
        logger.info("Chart cache hit (In-Memory) for SQL.")
        return val
    return None


def set_cached_chart(sql: str, chart: dict[str, Any]) -> None:
    """Store chart suggestion in cache."""
    cache_key = f"chart:{_get_hash_key(sql)}"
    
    if _redis_client:
        try:
            serialized = json.dumps(chart, default=str)
            _redis_client.setex(cache_key, settings.results_cache_ttl, serialized)
            return
        except Exception as e:
            logger.warning("Redis write error in set_cached_chart: %s", e)
            
    _chart_cache[cache_key] = chart


def clear_all_caches() -> None:
    """Flushes both the in-memory caches and Redis keys (if Redis is active)."""
    _sql_cache.clear()
    _results_cache.clear()
    _chart_cache.clear()
    _report_cache.clear()
    logger.info("In-memory caches cleared.")
    
    if _redis_client:
        try:
            # Flush keys belonging to analyst_agent
            keys = (
                _redis_client.keys("sql:*")
                + _redis_client.keys("results:*")
                + _redis_client.keys("chart:*")
                + _redis_client.keys("report:*")
            )
            if keys:
                _redis_client.delete(*keys)
            logger.info("Redis caches cleared.")
        except Exception as e:
            logger.warning("Failed to clear Redis caches: %s", e)
