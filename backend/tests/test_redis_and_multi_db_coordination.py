import time
import pytest
from unittest.mock import MagicMock, patch
from app.services.database.system_store import SystemStore
from app.services.database.redis_store import RedisCoordinator, reset_redis_coordinator
from app.core.middleware.rate_limit import consume_rate_limit, clear_ram_rate_limits


def test_system_store_sqlite_in_memory():
    """Verify SystemStore works cleanly in in-memory mode."""
    store = SystemStore("sqlite:///:memory:")

    # 1. Sessions
    assert store.get_session_url("s1") is None
    assert store.set_session_url("s1", "postgresql://user:pass@localhost:5432/testdb")
    assert store.get_session_url("s1") == "postgresql://user:pass@localhost:5432/testdb"

    # Upsert
    assert store.set_session_url("s1", "sqlite:///new.db")
    assert store.get_session_url("s1") == "sqlite:///new.db"

    # 2. General Cache
    assert store.get_cache("key1") is None
    assert store.set_cache("key1", "val1", ttl_seconds=100)
    assert store.get_cache("key1") == "val1"
    store.clear_cache()
    assert store.get_cache("key1") is None

    # 3. Long-Term Memory
    assert store.get_memory("user_1", "prefs") is None
    assert store.set_memory("user_1", "prefs", {"theme": "dark", "lang": "en"})
    mem = store.get_memory("user_1", "prefs")
    assert mem == {"theme": "dark", "lang": "en"}
    assert store.delete_memory("user_1", "prefs")
    assert store.get_memory("user_1", "prefs") is None

    # 4. Schema Cache & Catalog Progress
    assert store.get_schema_cache("hash_abc") is None
    assert store.set_schema_cache("hash_abc", {"tables": ["t1", "t2"]})
    assert store.get_schema_cache("hash_abc") == {"tables": ["t1", "t2"]}

    assert store.get_catalog_progress("hash_abc") == {}
    assert store.set_catalog_progress("hash_abc", {"status": "complete", "total": 10})
    assert store.get_catalog_progress("hash_abc") == {"status": "complete", "total": 10}


def test_system_store_postgresql_url_handling():
    """Verify postgres:// and postgresql:// URLs are normalized and configured with QueuePool."""
    with patch("app.services.database.system_store.create_engine") as mock_engine:
        store = SystemStore("postgres://postgres:password@localhost:5432/mydb")
        assert "postgresql+psycopg2://" in store.db_url
        assert not store.is_sqlite
        assert mock_engine.called


def test_redis_coordinator_fallback_when_unconfigured():
    """Verify RedisCoordinator gracefully falls back when redis_url is None or offline."""
    coord = RedisCoordinator(redis_url=None)
    assert not coord.is_available()
    assert coord.get("k") is None
    assert coord.set("k", "v") is False
    assert coord.delete("k") is False

    # Job lock fallback succeeds locally
    with coord.acquire_lock("catalog_job") as acquired:
        assert acquired is True

    # Rate limiting falls back gracefully
    assert coord.consume_rate_limit("client_1", max_requests=10) is True


def test_redis_coordinator_with_mocked_redis_client():
    """Verify RedisCoordinator functions with an active Redis instance."""
    mock_redis = MagicMock()
    mock_redis.ping.return_value = True
    mock_redis.get.return_value = "cached_val"
    mock_redis.set.return_value = True
    mock_redis.delete.return_value = 1
    mock_redis.eval.return_value = 1

    coord = RedisCoordinator(redis_url="redis://localhost:6379/0")
    coord._client = mock_redis

    assert coord.is_available() is True
    assert coord.get("test_key") == "cached_val"
    assert coord.set("test_key", "val", ttl_seconds=60) is True
    assert coord.delete("test_key") is True
    assert coord.consume_rate_limit("ip_123", max_requests=5, window_seconds=60) is True

    # Lock acquisition
    mock_redis.set.return_value = True
    with coord.acquire_lock("test_job", timeout_seconds=1.0) as locked:
        assert locked is True
        assert mock_redis.set.called


def test_rate_limit_middleware_delegates_to_redis_or_ram():
    """Verify consume_rate_limit checks Redis coordinator and falls back to in-RAM."""
    clear_ram_rate_limits()

    # In-RAM test
    assert consume_rate_limit("192.168.1.1", max_requests=2, window_seconds=60.0) is True
    assert consume_rate_limit("192.168.1.1", max_requests=2, window_seconds=60.0) is True
    assert consume_rate_limit("192.168.1.1", max_requests=2, window_seconds=60.0) is False

    clear_ram_rate_limits()
