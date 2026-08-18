"""API rate limiting (High-performance in-RAM Token Bucket with 0ms overhead)."""
from __future__ import annotations

import time
import threading
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

from app.config.settings import settings
from app.database.redis_store import get_redis_coordinator

logger = structlog.get_logger(__name__)

_RATE_LIMITED_PATH_PREFIXES = ("/chat",)

# In-memory fast token bucket store: client_key -> (tokens, last_refreshed_monotonic)
_RAM_RATE_LIMIT_BUCKETS: dict[str, tuple[float, float]] = {}
_RAM_RATE_LIMIT_LOCK = threading.Lock()


def consume_rate_limit_ram(client_key: str, max_requests: int, window_seconds: float = 60.0) -> bool:
    """Fast, thread-safe in-RAM token bucket rate limiter without external overhead."""
    now = time.monotonic()
    with _RAM_RATE_LIMIT_LOCK:
        tokens, last_time = _RAM_RATE_LIMIT_BUCKETS.get(client_key, (float(max_requests), now))
        # Refill tokens proportional to elapsed time
        elapsed = max(0.0, now - last_time)
        tokens = min(float(max_requests), tokens + elapsed * (max_requests / window_seconds))

        if tokens >= 1.0:
            _RAM_RATE_LIMIT_BUCKETS[client_key] = (tokens - 1.0, now)
            return True

        _RAM_RATE_LIMIT_BUCKETS[client_key] = (tokens, now)
        return False


def consume_rate_limit(client_key: str, max_requests: int, window_seconds: float = 60.0) -> bool:
    """Evaluate rate limit using distributed Redis if available, otherwise in-RAM token bucket."""
    redis_coord = get_redis_coordinator()
    if redis_coord.is_available():
        return redis_coord.consume_rate_limit(client_key, max_requests, window_seconds)
    return consume_rate_limit_ram(client_key, max_requests, window_seconds)


def clear_ram_rate_limits() -> None:
    with _RAM_RATE_LIMIT_LOCK:
        _RAM_RATE_LIMIT_BUCKETS.clear()


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int | None = None):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute or settings.rate_limit_requests_per_minute

    async def dispatch(self, request: Request, call_next):
        if not settings.enable_rate_limit or not request.url.path.startswith(_RATE_LIMITED_PATH_PREFIXES):
            return await call_next(request)

        client_key = request.client.host if request.client else "unknown"
        allowed = consume_rate_limit(client_key, self.requests_per_minute, window_seconds=60.0)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "detail": (
                        f"Rate limit exceeded ({self.requests_per_minute} requests/minute). "
                        "Please slow down and try again shortly."
                    )
                },
            )
        return await call_next(request)
