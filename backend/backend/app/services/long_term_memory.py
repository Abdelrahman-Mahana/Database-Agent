"""Phase 7 — long-term memory (saved queries + preferences), separate from
`app/services/memory.py`'s per-session sliding-window conversation memory.

Storage: Embedded local SQLite system store with in-process fallback.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field, asdict
from typing import Any
import structlog

from app.database.system_store import system_store

logger = structlog.get_logger(__name__)

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

    # -- Saved queries ----------------------------------------------------

    def save_query(self, user_id: str, question: str, sql: str, label: str = "") -> SavedQuery:
        qid = hashlib.sha256(f"{user_id}:{question}:{sql}:{time.time()}".encode()).hexdigest()[:16]
        saved = SavedQuery(id=qid, question=question, sql=sql, label=label)

        existing = self.list_saved_queries(user_id)
        existing.append(saved)
        self._write_queries(user_id, existing)
        return saved

    def list_saved_queries(self, user_id: str) -> list[SavedQuery]:
        data = system_store.get_memory(user_id, "queries")
        if data is not None:
            return [SavedQuery(**i) for i in data]
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
        if system_store.set_memory(user_id, "queries", serialized):
            return
        _local_store.setdefault(user_id, {})["queries"] = serialized

    # -- Preferences --------------------------------------------------------

    def set_preference(self, user_id: str, key: str, value: Any) -> None:
        prefs = self.get_preferences(user_id)
        prefs[key] = value
        if system_store.set_memory(user_id, "prefs", prefs):
            return
        _local_store.setdefault(user_id, {})["preferences"] = prefs

    def get_preferences(self, user_id: str) -> dict[str, Any]:
        data = system_store.get_memory(user_id, "prefs")
        if data is not None:
            return data
        return dict(_local_store.get(user_id, {}).get("preferences", {}))


long_term_memory = LongTermMemoryStore()
