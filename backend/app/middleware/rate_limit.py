"""Phase 10 — API rate limiting.

A simple in-process token-bucket limiter, keyed by client IP (falling back
to a shared bucket if the IP can't be determined, e.g. behind certain
proxies without X-Forwarded-For configured). Deliberately NOT Redis-backed:
rate limiting is inherently per-process/per-edge in most simple deployments
of this project (single container, no shared state needed for "don't let
one client hammer the LLM endpoint"), and adding a Redis round-trip to
every single request just to check a counter is the wrong cost/benefit
trade for what this project's deployment profile actually needs. If you
scale to multiple workers behind a real load balancer, put this at the
load balancer / API gateway layer instead — that's genuinely a better fit
than trying to coordinate in-process counters across processes.

Only applies to `/chat` (the expensive, LLM-calling endpoint) — health
checks and static schema reads are cheap and shouldn't be throttled the
same way.
"""
from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

_RATE_LIMITED_PATH_PREFIXES = ("/chat",)


class _TokenBucket:
    def __init__(self, rate_per_minute: int):
        self.capacity = max(1, rate_per_minute)
        self.tokens = float(self.capacity)
        self.refill_rate_per_sec = self.capacity / 60.0
        self.last_refill = time.monotonic()

    def try_consume(self) -> bool:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate_per_sec)
        self.last_refill = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int | None = None):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute or settings.rate_limit_requests_per_minute
        self._buckets: dict[str, _TokenBucket] = defaultdict(lambda: _TokenBucket(self.requests_per_minute))
        self._lock = Lock()

    async def dispatch(self, request: Request, call_next):
        if not settings.enable_rate_limit or not request.url.path.startswith(_RATE_LIMITED_PATH_PREFIXES):
            return await call_next(request)

        client_key = request.client.host if request.client else "unknown"
        with self._lock:
            bucket = self._buckets[client_key]
            allowed = bucket.try_consume()

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
