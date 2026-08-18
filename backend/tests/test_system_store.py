import time
import pytest
from pathlib import Path
from app.database.system_store import SystemStore


@pytest.fixture
def temp_store(tmp_path: Path):
    db_file = tmp_path / "test_store.db"
    store = SystemStore(db_path=db_file)
    return store


def test_session_management(temp_store: SystemStore):
    assert temp_store.get_session_url("s1") is None
    temp_store.set_session_url("s1", "sqlite:///test1.db")
    assert temp_store.get_session_url("s1") == "sqlite:///test1.db"

    # Update session
    temp_store.set_session_url("s1", "sqlite:///updated.db")
    assert temp_store.get_session_url("s1") == "sqlite:///updated.db"


def test_cache_operations(temp_store: SystemStore):
    # Set and get valid cache
    temp_store.set_cache("sql:key1", "SELECT 1;", ttl_seconds=10)
    assert temp_store.get_cache("sql:key1") == "SELECT 1;"

    # Expired cache
    temp_store.set_cache("sql:expired", "SELECT 2;", ttl_seconds=-1)
    assert temp_store.get_cache("sql:expired") is None

    # Clear cache with prefix
    temp_store.set_cache("report:r1", "Report 1", ttl_seconds=60)
    temp_store.set_cache("sql:key2", "SELECT 3;", ttl_seconds=60)
    temp_store.clear_cache(prefix="sql:")
    assert temp_store.get_cache("sql:key2") is None
    assert temp_store.get_cache("report:r1") == "Report 1"

    # Clear all cache
    temp_store.clear_cache()
    assert temp_store.get_cache("report:r1") is None


def test_rate_limiting(temp_store: SystemStore):
    client_ip = "127.0.0.1"
    capacity = 3
    window_seconds = 60.0

    # Consume available tokens
    assert temp_store.consume_rate_limit(client_ip, capacity, window_seconds) is True
    assert temp_store.consume_rate_limit(client_ip, capacity, window_seconds) is True
    assert temp_store.consume_rate_limit(client_ip, capacity, window_seconds) is True

    # 4th request should be rejected
    assert temp_store.consume_rate_limit(client_ip, capacity, window_seconds) is False


def test_in_ram_rate_limiting_and_hot_cache_isolation():
    from app.middleware.rate_limit import consume_rate_limit_ram, clear_ram_rate_limits
    from app.utils.cache import get_cached_sql, set_cached_sql, _sql_cache

    # 1. Test fast in-RAM token bucket
    clear_ram_rate_limits()
    client = "192.168.1.50"
    assert consume_rate_limit_ram(client, max_requests=2) is True
    assert consume_rate_limit_ram(client, max_requests=2) is True
    assert consume_rate_limit_ram(client, max_requests=2) is False

    # 2. Test in-RAM hot cache lookup (0ms)
    set_cached_sql("Count active users", "users(id)", "SELECT COUNT(*) FROM users;")
    # Verify present in L1 RAM cache directly
    cached_sql, _ = get_cached_sql("Count active users", "users(id)")
    assert cached_sql == "SELECT COUNT(*) FROM users;"


def test_long_term_memory(temp_store: SystemStore):
    user_id = "user_123"
    queries = [{"id": "q1", "question": "top sales", "sql": "SELECT * FROM sales"}]
    prefs = {"theme": "dark", "model": "fast"}

    temp_store.set_memory(user_id, "queries", queries)
    temp_store.set_memory(user_id, "prefs", prefs)

    assert temp_store.get_memory(user_id, "queries") == queries
    assert temp_store.get_memory(user_id, "prefs") == prefs

    temp_store.delete_memory(user_id, "queries")
    assert temp_store.get_memory(user_id, "queries") is None
    assert temp_store.get_memory(user_id, "prefs") == prefs


def test_schema_cache_and_catalog_progress(temp_store: SystemStore):
    db_hash = "db_hash_abc"
    schema_data = {"schema": {"users": {"columns": []}}}
    progress_data = {"progress": 100, "status": "done"}

    temp_store.set_schema_cache(db_hash, schema_data)
    assert temp_store.get_schema_cache(db_hash) == schema_data

    temp_store.set_catalog_progress(db_hash, progress_data)
    assert temp_store.get_catalog_progress(db_hash) == progress_data

    temp_store.clear_schema_cache(db_hash_prefix="db_hash_")
    assert temp_store.get_schema_cache(db_hash) is None
