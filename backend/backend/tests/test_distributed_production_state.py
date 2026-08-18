import pytest
import time
from app.utils.cache import (
    get_cached_sql,
    set_cached_sql,
    get_cached_results,
    set_cached_results,
    clear_all_caches,
)
from app.database.redis_store import RedisCoordinator, reset_redis_coordinator
from app.database.system_store import SystemStore
from app.jobs.durable_queue import DurableJobQueue


class MockRedisClient:
    """Mock Redis client simulating Redis server operations in RAM for testing."""
    def __init__(self):
        self.data = {}
        self.ttls = {}

    def ping(self):
        return True

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return False
        self.data[key] = value
        self.ttls[key] = ex
        return True

    def delete(self, key):
        return self.data.pop(key, None) is not None

    def eval(self, script, numkeys, *args):
        # Handle lock release script
        if 'if redis.call("get", KEYS[1]) == ARGV[1]' in script:
            key, token = args[0], args[1]
            if self.data.get(key) == token:
                del self.data[key]
                return 1
            return 0
        # Handle rate limit sliding window script
        key = args[0]
        now = float(args[1])
        clear_before = float(args[2])
        max_req = int(args[3])

        timestamps = self.data.setdefault(key, [])
        valid_ts = [t for t in timestamps if t > clear_before]
        if len(valid_ts) < max_req:
            valid_ts.append(now)
            self.data[key] = valid_ts
            return 1
        self.data[key] = valid_ts
        return 0


def test_three_tier_caching_with_redis(monkeypatch, tmp_path):
    """Test L1 RAM -> L2 Redis -> L3 SystemStore multi-tier caching hierarchy."""
    # 1. Setup mock redis coordinator
    mock_coord = RedisCoordinator(redis_url="redis://localhost:6379/0")
    mock_client = MockRedisClient()
    mock_coord._client = mock_client
    monkeypatch.setattr("app.utils.cache.get_redis_coordinator", lambda: mock_coord)

    # 2. Setup isolated SQLite system store
    store = SystemStore(db_url_or_path=str(tmp_path / "system.db"))
    monkeypatch.setattr("app.utils.cache.system_store", store)

    clear_all_caches()

    # Store SQL query in cache
    set_cached_sql(
        question="Show all active orders",
        schema_text="orders(id, status)",
        sql="SELECT * FROM orders WHERE status = 'active'",
        database_fingerprint="fp_tier_test",
        dialect="sqlite",
    )

    # Verify L2 Redis contains the serialized entry
    keys_in_redis = list(mock_client.data.keys())
    assert any("sql:" in k for k in keys_in_redis)

    # Clear L1 RAM cache to force L2 Redis retrieval
    from app.utils.cache import _sql_cache
    _sql_cache.clear()

    sql, meta = get_cached_sql(
        question="Show all active orders",
        schema_text="orders(id, status)",
        database_fingerprint="fp_tier_test",
        dialect="sqlite",
    )
    assert sql == "SELECT * FROM orders WHERE status = 'active'"


def test_redis_sliding_window_rate_limiting():
    """Test distributed atomic sliding window rate limiter."""
    coord = RedisCoordinator(redis_url="redis://localhost:6379/0")
    coord._client = MockRedisClient()

    client_ip = "192.168.1.100"
    max_requests = 3
    window_seconds = 10.0

    # First 3 requests must succeed
    assert coord.consume_rate_limit(client_ip, max_requests=max_requests, window_seconds=window_seconds) is True
    assert coord.consume_rate_limit(client_ip, max_requests=max_requests, window_seconds=window_seconds) is True
    assert coord.consume_rate_limit(client_ip, max_requests=max_requests, window_seconds=window_seconds) is True

    # 4th request in same window must be blocked
    assert coord.consume_rate_limit(client_ip, max_requests=max_requests, window_seconds=window_seconds) is False


def test_distributed_redis_mutex_lock():
    """Test distributed lock acquisition and release."""
    coord = RedisCoordinator(redis_url="redis://localhost:6379/0")
    coord._client = MockRedisClient()

    lock_key = "onboard:test_fingerprint"

    # Acquire lock
    with coord.acquire_lock(lock_key, timeout_seconds=1.0, lock_timeout=30.0) as acquired:
        assert acquired is True
        assert f"lock:{lock_key}" in coord._client.data

    # After context exit, lock should be released
    assert f"lock:{lock_key}" not in coord._client.data


def test_durable_job_queue_idempotency_and_recovery(tmp_path, monkeypatch):
    """Test DurableJobQueue idempotent submission, status tracking, and stalled job recovery."""
    store = SystemStore(db_url_or_path=str(tmp_path / "durable_system.db"))
    queue = DurableJobQueue(store=store)

    fp = "fp_durable_test_123"
    db_url = "sqlite:///:memory:"

    # Prevent background execution during synchronous unit test
    async def mock_run(jid):
        pass
    monkeypatch.setattr(queue, "run_onboarding_job", mock_run)

    # 1. Submit onboarding job
    job1 = queue.submit_onboarding_job(database_url=db_url, fingerprint=fp)
    assert job1["job_id"] is not None
    assert job1["status"] in ("pending", "running")

    # 2. Idempotent re-submission returns existing job
    job2 = queue.submit_onboarding_job(database_url=db_url, fingerprint=fp)
    assert job2["job_id"] == job1["job_id"]

    # 3. Simulate stalled worker crash (running status with old updated_at)
    jid = job1["job_id"]
    store.update_job_status(jid, status="running", progress_percent=40.0, stage="profiling")

    # Manually backdate updated_at by 15 minutes (900 seconds)
    with store.engine.connect() as conn:
        from sqlalchemy import text
        old_time = time.time() - 900
        conn.execute(text("UPDATE agent_jobs SET updated_at = :t WHERE job_id = :jid"), {"t": old_time, "jid": jid})
        conn.commit()

    # 4. Recover stalled jobs
    recovered = queue.recover_stalled_jobs(stalled_threshold_seconds=600.0)
    assert jid in recovered

    updated_job = queue.get_job(jid)
    assert updated_job["status"] == "pending"
    assert updated_job["stage"] == "recovered"
