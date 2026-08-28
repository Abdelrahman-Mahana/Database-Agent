"""Distributed Redis store for cross-worker cache, rate limiting, and job locks.

Provides seamless distributed coordination when redis_url is configured, with
graceful fallbacks to local in-memory execution when Redis is offline or not configured.
"""
from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator, Optional
import structlog

logger = structlog.get_logger(__name__)

try:
    import redis
except ImportError:
    redis = None


class RedisLock:
    """Context manager for distributed Redis locks."""

    def __init__(self, client: Optional[Any], lock_name: str, token: str, lock_timeout: float):
        self.client = client
        self.lock_name = f"lock:{lock_name}"
        self.token = token
        self.lock_timeout = lock_timeout
        self.acquired = False

    def __enter__(self) -> bool:
        return self.acquired

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.acquired and self.client is not None:
            # Release lock only if token matches (prevents releasing expired locks held by others)
            release_lua = """
                if redis.call("get", KEYS[1]) == ARGV[1] then
                    return redis.call("del", KEYS[1])
                else
                    return 0
                end
            """
            try:
                self.client.eval(release_lua, 1, self.lock_name, self.token)
            except Exception as e:
                logger.warning("Failed to release Redis lock", lock=self.lock_name, error=str(e))


class RedisCoordinator:
    """High-performance Redis coordinator for multi-worker / multi-node deployments."""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url
        self._client: Optional[Any] = None
        self._is_connected: Optional[bool] = None

        if self.redis_url and redis is not None:
            try:
                self._client = redis.Redis.from_url(
                    self.redis_url,
                    socket_timeout=2.0,
                    socket_connect_timeout=2.0,
                    decode_responses=True,
                )
            except Exception as exc:
                logger.warning("Redis initialization error", url=self.redis_url, error=str(exc))
                self._client = None

    def is_available(self) -> bool:
        """Check if Redis connection is active and responsive."""
        if self._client is None:
            return False
        try:
            return bool(self._client.ping())
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # Distributed Cache Operations
    # -------------------------------------------------------------------------

    def get(self, key: str) -> Optional[str]:
        """Fetch string value from Redis cache."""
        if not self.is_available():
            return None
        try:
            return self._client.get(key)
        except Exception as e:
            logger.warning("Redis get failed", key=key, error=str(e))
            return None

    def set(self, key: str, value: str, ttl_seconds: int = 3600) -> bool:
        """Store string value in Redis cache with TTL."""
        if not self.is_available():
            return False
        try:
            return bool(self._client.set(key, value, ex=ttl_seconds))
        except Exception as e:
            logger.warning("Redis set failed", key=key, error=str(e))
            return False

    def delete(self, key: str) -> bool:
        """Delete key from Redis cache."""
        if not self.is_available():
            return False
        try:
            return bool(self._client.delete(key))
        except Exception as e:
            logger.warning("Redis delete failed", key=key, error=str(e))
            return False

    # -------------------------------------------------------------------------
    # Distributed Atomic Rate Limiting (Token Bucket / Sliding Window)
    # -------------------------------------------------------------------------

    def consume_rate_limit(
        self,
        client_key: str,
        max_requests: int,
        window_seconds: float = 60.0,
    ) -> bool:
        """
        Atomic sliding window rate limiter in Redis.
        Returns True if request is allowed, False if rate limited.
        """
        if not self.is_available():
            return True  # Fallback gracefully if Redis is unavailable

        redis_key = f"ratelimit:{client_key}"
        now = time.time()
        clear_before = now - window_seconds

        # Atomic sliding window pipeline:
        # 1. Remove entries older than the window
        # 2. Count entries in current window
        # 3. If count < max_requests, add current timestamp
        # 4. Set TTL on key
        lua_script = """
            local key = KEYS[1]
            local now = tonumber(ARGV[1])
            local clear_before = tonumber(ARGV[2])
            local max_reqs = tonumber(ARGV[3])
            local window = tonumber(ARGV[4])

            redis.call('ZREMRANGEBYSCORE', key, 0, clear_before)
            local current_reqs = redis.call('ZCARD', key)

            if current_reqs < max_reqs then
                redis.call('ZADD', key, now, now)
                redis.call('EXPIRE', key, math.ceil(window))
                return 1
            else
                return 0
            end
        """
        try:
            res = self._client.eval(lua_script, 1, redis_key, str(now), str(clear_before), str(max_requests), str(window_seconds))
            return bool(res == 1)
        except Exception as exc:
            logger.warning("Redis rate limit evaluation failed", client=client_key, error=str(exc))
            return True

    # -------------------------------------------------------------------------
    # Distributed Job Locks (Mutex)
    # -------------------------------------------------------------------------

    @contextmanager
    def acquire_lock(
        self,
        lock_name: str,
        timeout_seconds: float = 10.0,
        lock_timeout: float = 30.0,
    ) -> Iterator[bool]:
        """
        Acquire a distributed lock with automatic expiration.
        Yields True if acquired, False if timeout reached.
        """
        if not self.is_available():
            # In-process fallback: yield True when Redis is not present
            yield True
            return

        token = str(uuid.uuid4())
        lock_key = f"lock:{lock_name}"
        deadline = time.monotonic() + timeout_seconds
        acquired = False

        while time.monotonic() < deadline:
            try:
                # NX: set only if not exists, EX: expire in seconds
                if self._client.set(lock_key, token, nx=True, ex=int(lock_timeout)):
                    acquired = True
                    break
            except Exception as e:
                logger.warning("Redis lock acquisition failed", lock=lock_name, error=str(e))
                break
            time.sleep(0.05)

        lock_ctx = RedisLock(self._client, lock_name, token, lock_timeout)
        lock_ctx.acquired = acquired
        try:
            yield acquired
        finally:
            if acquired:
                lock_ctx.__exit__(None, None, None)


_REDIS_COORDINATOR: Optional[RedisCoordinator] = None


def get_redis_coordinator() -> RedisCoordinator:
    """Get or initialize singleton Redis coordinator."""
    global _REDIS_COORDINATOR
    if _REDIS_COORDINATOR is None:
        from app.core.config.settings import settings
        _REDIS_COORDINATOR = RedisCoordinator(redis_url=settings.redis_url)
    return _REDIS_COORDINATOR


def reset_redis_coordinator(redis_url: Optional[str] = None) -> RedisCoordinator:
    """Reset the singleton (useful for testing)."""
    global _REDIS_COORDINATOR
    _REDIS_COORDINATOR = RedisCoordinator(redis_url=redis_url)
    return _REDIS_COORDINATOR
