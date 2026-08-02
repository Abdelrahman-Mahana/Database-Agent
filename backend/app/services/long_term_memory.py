"""Phase 7 — long-term memory (saved queries + preferences), separate from
`app/services/memory.py`'s per-session sliding-window conversation memory.

That module intentionally forgets everything when a session expires (by
design — it's short-term working memory for follow-up questions within one
conversation). This module is for things a user explicitly wants kept
*across* sessions: a favorite/frequently-run query they want one click away,
or a lightweight preference (preferred chart type, preferred language for
reports).

Storage: Redis when `settings.redis_url` is configured (persists across
restarts, shared across workers) — otherwise an in-process dict (lost on
restart, single-worker only). This mirrors the exact fallback pattern
already used in `app/utils/cache.py`, rather than introducing a second,
different persistence mechanism.

This module is deliberately NOT wired into the main `AnalystAgent.ask()`
pipeline — saved queries / preferences are something a user opts into via
an explicit action (a "save this" button, a settings screen), not something
that should silently change how every question is answered. See
`app/api/memory.py` for the endpoints that expose it.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from loguru import logger

from app.core.config import settings

_redis_client = None
if settings.redis_url:
    try:
        import redis
        _redis_client = redis.from_url(settings.redis_url)
    except ImportError:
        logger.warning("redis-py not installed — long-term memory will use in-process storage only.")
    except Exception as e:
        logger.warning("Failed to connect to Redis at %s for long-term memory: %s", settings.redis_url, e)

# In-process fallback store: user_id -> {"queries": [...], "preferences": {...}}
_local_store: dict[str, dict[str, Any]] = {}


@dataclass
class SavedQuery:
    id: str
    question: str
    sql: str
    label: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LongTermMemoryStore:
    """Per-user saved queries and preferences."""

    def _key(self, user_id: str, sub: str) -> str:
        return f"ltm:{sub}:{user_id}"

    # -- Saved queries ----------------------------------------------------

    def save_query(self, user_id: str, question: str, sql: str, label: str = "") -> SavedQuery:
        import hashlib
        qid = hashlib.sha256(f"{user_id}:{question}:{sql}:{time.time()}".encode()).hexdigest()[:16]
        saved = SavedQuery(id=qid, question=question, sql=sql, label=label)

        existing = self.list_saved_queries(user_id)
        existing.append(saved)
        self._write_queries(user_id, existing)
        return saved

    def list_saved_queries(self, user_id: str) -> list[SavedQuery]:
        if _redis_client:
            try:
                raw = _redis_client.get(self._key(user_id, "queries"))
                if raw:
                    items = json.loads(raw.decode("utf-8"))
                    return [SavedQuery(**i) for i in items]
                return []
            except Exception as e:
                logger.warning("Redis read error in list_saved_queries: %s", e)
        return [SavedQuery(**i) for i in _local_store.get(user_id, {}).get("queries", [])]

    def delete_saved_query(self, user_id: str, query_id: str) -> bool:
        existing = self.list_saved_queries(user_id)
        filtered = [q for q in existing if q.id != query_id]
        if len(filtered) == len(existing):
            return False
        self._write_queries(user_id, filtered)
        return True

    def _write_queries(self, user_id: str, queries: list[SavedQuery]) -> None:
        serialized = [q.to_dict() for q in queries]
        if _redis_client:
            try:
                _redis_client.set(self._key(user_id, "queries"), json.dumps(serialized))
                return
            except Exception as e:
                logger.warning("Redis write error in _write_queries: %s", e)
        _local_store.setdefault(user_id, {})["queries"] = serialized

    # -- Preferences --------------------------------------------------------

    def set_preference(self, user_id: str, key: str, value: Any) -> None:
        prefs = self.get_preferences(user_id)
        prefs[key] = value
        if _redis_client:
            try:
                _redis_client.set(self._key(user_id, "prefs"), json.dumps(prefs))
                return
            except Exception as e:
                logger.warning("Redis write error in set_preference: %s", e)
        _local_store.setdefault(user_id, {})["preferences"] = prefs

    def get_preferences(self, user_id: str) -> dict[str, Any]:
        if _redis_client:
            try:
                raw = _redis_client.get(self._key(user_id, "prefs"))
                return json.loads(raw.decode("utf-8")) if raw else {}
            except Exception as e:
                logger.warning("Redis read error in get_preferences: %s", e)
        return dict(_local_store.get(user_id, {}).get("preferences", {}))


long_term_memory = LongTermMemoryStore()
