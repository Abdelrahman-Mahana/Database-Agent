"""Phase 8 — cost dashboard.

`app/utils/token_tracker.py` already captures prompt/completion tokens
per-request via a ContextVar (reset at the start of each `/chat` call). That
data was being read once (in `api/chat.py`) and then thrown away — never
aggregated, so there was no way to answer "how much are we actually
spending, broken down by question type" without grepping logs by hand.

This module is the aggregation layer: a lightweight in-process rolling
store (per-day, per-analysis-type) that `api/chat.py` records into after
every request, plus a rough USD cost estimate using a small static
$/1K-token pricing table (best-effort — exact pricing varies by provider
and changes over time; this is for relative cost-tracking / "did my last
change move the number", not an invoice).
"""
from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

# Rough $/1K-token pricing (prompt, completion), for relative cost tracking.
# Override/extend via settings if you need exact figures for a specific
# provider account — this is intentionally not wired to a live pricing API.
_DEFAULT_PRICING_PER_1K: dict[str, tuple[float, float]] = {
    "google/gemini-2.5-flash": (0.000075, 0.0003),
    "llama-3.3-70b-versatile": (0.00059, 0.00079),
    "llama-3.1-8b-instant": (0.00005, 0.00008),
}
_FALLBACK_PRICE_PER_1K = (0.0002, 0.0006)  # conservative generic estimate


def _estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    prompt_price, completion_price = _DEFAULT_PRICING_PER_1K.get(model, _FALLBACK_PRICE_PER_1K)
    return (prompt_tokens / 1000) * prompt_price + (completion_tokens / 1000) * completion_price


@dataclass
class _Bucket:
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0


@dataclass
class UsageRecord:
    timestamp: float
    session_id: Optional[str]
    analysis_type: Optional[str]
    model: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float


class CostDashboard:
    """Thread-safe in-process aggregator. Resets on process restart —
    for durable cross-restart history, point this at the same Redis
    instance used elsewhere (left as a documented extension point rather
    than a forced dependency for every deployment size)."""

    def __init__(self, max_recent_records: int = 500):
        self._lock = Lock()
        self._by_day: dict[str, _Bucket] = defaultdict(_Bucket)
        self._by_analysis_type: dict[str, _Bucket] = defaultdict(_Bucket)
        self._recent: list[UsageRecord] = []
        self._max_recent = max_recent_records

    def record(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: str = "unknown",
        session_id: Optional[str] = None,
        analysis_type: Optional[str] = None,
    ) -> UsageRecord:
        cost = _estimate_cost_usd(model, prompt_tokens, completion_tokens)
        day_key = time.strftime("%Y-%m-%d", time.gmtime())
        record = UsageRecord(
            timestamp=time.time(),
            session_id=session_id,
            analysis_type=analysis_type,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated_cost_usd=cost,
        )
        with self._lock:
            day_bucket = self._by_day[day_key]
            day_bucket.requests += 1
            day_bucket.prompt_tokens += prompt_tokens
            day_bucket.completion_tokens += completion_tokens
            day_bucket.estimated_cost_usd += cost

            type_key = analysis_type or "unknown"
            type_bucket = self._by_analysis_type[type_key]
            type_bucket.requests += 1
            type_bucket.prompt_tokens += prompt_tokens
            type_bucket.completion_tokens += completion_tokens
            type_bucket.estimated_cost_usd += cost

            self._recent.append(record)
            if len(self._recent) > self._max_recent:
                self._recent.pop(0)
        return record

    def summary(self) -> dict:
        with self._lock:
            total_prompt = sum(b.prompt_tokens for b in self._by_day.values())
            total_comp = sum(b.completion_tokens for b in self._by_day.values())
            total_cost = sum(b.estimated_cost_usd for b in self._by_day.values())
            total_req = sum(b.requests for b in self._by_day.values())
            return {
                "by_day": {k: vars(v) for k, v in self._by_day.items()},
                "by_analysis_type": {k: vars(v) for k, v in self._by_analysis_type.items()},
                "recent_requests": len(self._recent),
                "total_estimated_cost_usd": total_cost,
                "estimated_cost_usd": total_cost,
                "total_requests": total_req,
                "requests_count": total_req,
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_comp,
                "total_tokens": total_prompt + total_comp,
            }

    def recent(self, limit: int = 50) -> list[UsageRecord]:
        with self._lock:
            return list(reversed(self._recent[-limit:]))


cost_dashboard = CostDashboard()
