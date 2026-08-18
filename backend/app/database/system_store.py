"""High-performance local SQLite storage for state, caching, sessions, and memory.

Replaces external cloud Supabase dependency with zero-latency, embedded SQLite.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional
import structlog

logger = structlog.get_logger(__name__)


class SystemStore:
    """Thread-safe SQLite system store using WAL mode for concurrent reads/writes."""

    def __init__(self, db_path: Optional[str | Path] = None):
        if db_path is None:
            try:
                from app.config.settings import settings
                self.db_path = str(settings.system_store_path)
            except Exception:
                backend_dir = Path(__file__).resolve().parents[2]
                self.db_path = str(backend_dir / "data" / "system_store.db")
        else:
            self.db_path = str(db_path)

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a connection configured with WAL mode and fast busy timeouts."""
        conn = sqlite3.connect(
            self.db_path,
            timeout=15.0,
            check_same_thread=False,
        )
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    def _init_db(self) -> None:
        """Initialize required system tables and indices."""
        with self._lock, self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    session_id TEXT PRIMARY KEY,
                    database_url TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_cache_expires_at ON agent_cache (expires_at);

                CREATE TABLE IF NOT EXISTS agent_rate_limits (
                    ip_address TEXT PRIMARY KEY,
                    tokens REAL NOT NULL,
                    last_refill REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_memory (
                    user_id TEXT NOT NULL,
                    sub TEXT NOT NULL,
                    data TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (user_id, sub)
                );

                CREATE TABLE IF NOT EXISTS agent_schema_cache (
                    db_hash TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_catalog_progress (
                    db_hash TEXT PRIMARY KEY,
                    progress TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)

    # -------------------------------------------------------------------------
    # 1. Session Management
    # -------------------------------------------------------------------------

    def get_session_url(self, session_id: str) -> Optional[str]:
        """Fetch the database URL mapped to a session ID."""
        try:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT database_url FROM agent_sessions WHERE session_id = ?",
                    (session_id,),
                )
                row = cur.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.warning("Error reading session from local store", error=str(e))
            return None

    def set_session_url(self, session_id: str, database_url: str) -> bool:
        """Store or update the database URL mapped to a session ID."""
        try:
            now = time.time()
            with self._lock, self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_sessions (session_id, database_url, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        database_url = excluded.database_url,
                        updated_at = excluded.updated_at
                    """,
                    (session_id, database_url, now),
                )
                return True
        except Exception as e:
            logger.warning("Error saving session to local store", error=str(e))
            return False

    # -------------------------------------------------------------------------
    # 2. General Key-Value Cache with TTL
    # -------------------------------------------------------------------------

    def get_cache(self, key: str) -> Optional[str]:
        """Fetch value from cache if it exists and has not expired."""
        try:
            now = time.time()
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT value, expires_at FROM agent_cache WHERE key = ?",
                    (key,),
                )
                row = cur.fetchone()
                if not row:
                    return None

                val, expires_at = row
                if now <= expires_at:
                    return val

                # Lazy cleanup for expired key
                conn.execute("DELETE FROM agent_cache WHERE key = ?", (key,))
                return None
        except Exception as e:
            logger.warning("Error reading from local cache store", error=str(e))
            return None

    def set_cache(self, key: str, value: str, ttl_seconds: int) -> bool:
        """Write key-value with TTL to cache store."""
        try:
            expires_at = time.time() + ttl_seconds
            with self._lock, self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_cache (key, value, expires_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        expires_at = excluded.expires_at
                    """,
                    (key, value, expires_at),
                )
                return True
        except Exception as e:
            logger.warning("Error writing to local cache store", error=str(e))
            return False

    def clear_cache(self, prefix: Optional[str] = None) -> bool:
        """Clear all or matching cache entries."""
        try:
            with self._lock, self._get_connection() as conn:
                if prefix:
                    conn.execute("DELETE FROM agent_cache WHERE key LIKE ?", (f"{prefix}%",))
                else:
                    conn.execute("DELETE FROM agent_cache")
                return True
        except Exception as e:
            logger.warning("Error clearing local cache store", error=str(e))
            return False

    # -------------------------------------------------------------------------
    # 3. Token-Bucket Rate Limiter
    # -------------------------------------------------------------------------

    def consume_rate_limit(self, client_key: str, capacity: int, window_seconds: float = 60.0) -> bool:
        """Atomic token bucket rate limiter in SQLite."""
        try:
            now = time.time()
            refill_rate = capacity / window_seconds
            with self._lock, self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT tokens, last_refill FROM agent_rate_limits WHERE ip_address = ?",
                    (client_key,),
                )
                row = cur.fetchone()

                if not row:
                    # First request from this client
                    conn.execute(
                        "INSERT INTO agent_rate_limits (ip_address, tokens, last_refill) VALUES (?, ?, ?)",
                        (client_key, float(capacity - 1), now),
                    )
                    return True

                tokens, last_refill = float(row[0]), float(row[1])
                elapsed = now - last_refill
                tokens = min(float(capacity), tokens + elapsed * refill_rate)

                if tokens >= 1.0:
                    tokens -= 1.0
                    conn.execute(
                        "UPDATE agent_rate_limits SET tokens = ?, last_refill = ? WHERE ip_address = ?",
                        (tokens, now, client_key),
                    )
                    return True
                else:
                    conn.execute(
                        "UPDATE agent_rate_limits SET tokens = ?, last_refill = ? WHERE ip_address = ?",
                        (tokens, now, client_key),
                    )
                    return False
        except Exception as e:
            logger.warning("Error in local rate limiter, failing open", error=str(e))
            return True  # Fail open

    # -------------------------------------------------------------------------
    # 4. Long-Term Memory (User Queries & Preferences)
    # -------------------------------------------------------------------------

    def get_memory(self, user_id: str, sub: str) -> Optional[Any]:
        """Fetch parsed JSON data from long-term memory."""
        try:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT data FROM agent_memory WHERE user_id = ? AND sub = ?",
                    (user_id, sub),
                )
                row = cur.fetchone()
                if row:
                    return json.loads(row[0])
                return None
        except Exception as e:
            logger.warning("Error reading from local memory store", error=str(e))
            return None

    def set_memory(self, user_id: str, sub: str, data: Any) -> bool:
        """Save JSON data to long-term memory."""
        try:
            serialized = json.dumps(data)
            now = time.time()
            with self._lock, self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_memory (user_id, sub, data, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, sub) DO UPDATE SET
                        data = excluded.data,
                        updated_at = excluded.updated_at
                    """,
                    (user_id, sub, serialized, now),
                )
                return True
        except Exception as e:
            logger.warning("Error saving to local memory store", error=str(e))
            return False

    def delete_memory(self, user_id: str, sub: str) -> bool:
        """Delete specific sub-memory for a user."""
        try:
            with self._lock, self._get_connection() as conn:
                conn.execute(
                    "DELETE FROM agent_memory WHERE user_id = ? AND sub = ?",
                    (user_id, sub),
                )
                return True
        except Exception as e:
            logger.warning("Error deleting from local memory store", error=str(e))
            return False

    # -------------------------------------------------------------------------
    # 5. Schema Service Cache & Catalog Progress
    # -------------------------------------------------------------------------

    def get_schema_cache(self, db_hash: str) -> Optional[dict[str, Any]]:
        """Fetch cached schema data for a database fingerprint."""
        try:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT data FROM agent_schema_cache WHERE db_hash = ?",
                    (db_hash,),
                )
                row = cur.fetchone()
                if row:
                    return json.loads(row[0])
                return None
        except Exception as e:
            logger.warning("Error reading schema cache from local store", error=str(e))
            return None

    def set_schema_cache(self, db_hash: str, data: dict[str, Any]) -> bool:
        """Persist schema cache entry for a database fingerprint."""
        try:
            serialized = json.dumps(data)
            now = time.time()
            with self._lock, self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_schema_cache (db_hash, data, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(db_hash) DO UPDATE SET
                        data = excluded.data,
                        updated_at = excluded.updated_at
                    """,
                    (db_hash, serialized, now),
                )
                return True
        except Exception as e:
            logger.warning("Error saving schema cache to local store", error=str(e))
            return False

    def clear_schema_cache(self, db_hash_prefix: Optional[str] = None) -> bool:
        """Clear all or matching schema cache entries."""
        try:
            with self._lock, self._get_connection() as conn:
                if db_hash_prefix:
                    conn.execute(
                        "DELETE FROM agent_schema_cache WHERE db_hash LIKE ?",
                        (f"{db_hash_prefix}%",),
                    )
                else:
                    conn.execute("DELETE FROM agent_schema_cache")
                return True
        except Exception as e:
            logger.warning("Error clearing schema cache in local store", error=str(e))
            return False

    def get_catalog_progress(self, db_hash: str) -> dict[str, Any]:
        """Fetch catalog build progress dict."""
        try:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT progress FROM agent_catalog_progress WHERE db_hash = ?",
                    (db_hash,),
                )
                row = cur.fetchone()
                if row:
                    return json.loads(row[0])
                return {}
        except Exception as e:
            logger.warning("Error reading catalog progress from local store", error=str(e))
            return {}

    def set_catalog_progress(self, db_hash: str, progress: dict[str, Any]) -> bool:
        """Save catalog build progress dict."""
        try:
            serialized = json.dumps(progress)
            now = time.time()
            with self._lock, self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO agent_catalog_progress (db_hash, progress, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(db_hash) DO UPDATE SET
                        progress = excluded.progress,
                        updated_at = excluded.updated_at
                    """,
                    (db_hash, serialized, now),
                )
                return True
        except Exception as e:
            logger.warning("Error saving catalog progress to local store", error=str(e))
            return False


# Singleton global instance
system_store = SystemStore()
