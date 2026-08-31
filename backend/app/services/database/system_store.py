"""Multi-engine System Store for durable state, sessions, caching, and memory.

Supports both PostgreSQL (for multi-worker / multi-node production deployments)
and SQLite (for embedded zero-dependency local development).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Optional
import structlog
from sqlalchemy import create_engine, text, event, Engine
from sqlalchemy.pool import StaticPool, QueuePool

logger = structlog.get_logger(__name__)


def _normalize_system_db_url(url: str) -> str:
    """Normalize system database connection URLs to use installed SQLAlchemy drivers."""
    u = url.strip()
    if u.startswith("postgres://"):
        u = "postgresql+psycopg2://" + u[len("postgres://"):]
    elif u.startswith("postgresql://") and not u.startswith("postgresql+"):
        u = "postgresql+psycopg2://" + u[len("postgresql://"):]
    return u


class SystemStore:
    """
    Thread-safe, multi-engine system store for sessions, cache, memory, and schema metadata.
    
    Supports:
    - PostgreSQL via SQLAlchemy QueuePool (multi-instance / distributed production)
    - SQLite via WAL mode + busy timeout (local single-instance dev)
    """

    def __init__(
        self,
        db_url_or_path: Optional[str | Path] = None,
        db_path: Optional[str | Path] = None,
    ):
        from app.core.config.settings import settings

        target = db_url_or_path if db_url_or_path is not None else db_path

        if target is None:
            if settings.system_store_database_url:
                self.db_url = _normalize_system_db_url(settings.system_store_database_url)
                self.db_path = str(settings.system_store_database_url)
            else:
                p = Path(settings.system_store_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                self.db_url = f"sqlite:///{p}"
                self.db_path = str(p)
        else:
            s = str(target)
            if s.startswith("sqlite://") or s.startswith("postgresql://") or s.startswith("postgres://"):
                self.db_url = _normalize_system_db_url(s)
                self.db_path = s
            else:
                p = Path(s)
                p.parent.mkdir(parents=True, exist_ok=True)
                self.db_url = f"sqlite:///{p}"
                self.db_path = str(p)

        self.is_sqlite = self.db_url.startswith("sqlite")
        self._lock = threading.RLock()
        self.engine = self._create_engine()
        self._init_db()

    def _create_engine(self) -> Engine:
        """Create dialect-optimized SQLAlchemy engine."""
        if self.is_sqlite:
            if ":memory:" in self.db_url:
                engine = create_engine(
                    self.db_url,
                    connect_args={"check_same_thread": False},
                    poolclass=StaticPool,
                )
            else:
                engine = create_engine(
                    self.db_url,
                    connect_args={"check_same_thread": False, "timeout": 15.0},
                )

            @event.listens_for(engine, "connect")
            def _set_sqlite_pragmas(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA journal_mode = WAL;")
                    cursor.execute("PRAGMA synchronous = NORMAL;")
                    cursor.execute("PRAGMA busy_timeout = 5000;")
                finally:
                    cursor.close()

            return engine
        else:
            # PostgreSQL engine for production multi-worker deployment
            return create_engine(
                self.db_url,
                poolclass=QueuePool,
                pool_size=10,
                max_overflow=20,
                pool_recycle=1800,
                pool_pre_ping=True,
            )

    def _init_db(self) -> None:
        """Initialize system tables and indexes across SQLite and PostgreSQL."""
        with self._lock, self.engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    session_id VARCHAR(255) PRIMARY KEY,
                    database_url TEXT NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    session_id TEXT PRIMARY KEY,
                    database_url TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_cache (
                    key VARCHAR(512) PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at DOUBLE PRECISION NOT NULL
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS agent_cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_cache_expires_at ON agent_cache (expires_at);"))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_rate_limits (
                    ip_address VARCHAR(255) PRIMARY KEY,
                    tokens DOUBLE PRECISION NOT NULL,
                    last_refill DOUBLE PRECISION NOT NULL
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS agent_rate_limits (
                    ip_address TEXT PRIMARY KEY,
                    tokens REAL NOT NULL,
                    last_refill REAL NOT NULL
                );
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_memory (
                    user_id VARCHAR(255) NOT NULL,
                    sub VARCHAR(255) NOT NULL,
                    data TEXT NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (user_id, sub)
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS agent_memory (
                    user_id TEXT NOT NULL,
                    sub TEXT NOT NULL,
                    data TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (user_id, sub)
                );
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_schema_cache (
                    db_hash VARCHAR(255) PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS agent_schema_cache (
                    db_hash TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_catalog_progress (
                    db_hash VARCHAR(255) PRIMARY KEY,
                    progress TEXT NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS agent_catalog_progress (
                    db_hash TEXT PRIMARY KEY,
                    progress TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_jobs (
                    job_id VARCHAR(255) PRIMARY KEY,
                    job_type VARCHAR(64) NOT NULL,
                    target_fingerprint VARCHAR(255) NOT NULL,
                    database_url TEXT NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    progress_percent DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    stage VARCHAR(64) NOT NULL DEFAULT '',
                    error TEXT,
                    created_at DOUBLE PRECISION NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL,
                    completed_at DOUBLE PRECISION
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS agent_jobs (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    target_fingerprint TEXT NOT NULL,
                    database_url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress_percent REAL NOT NULL DEFAULT 0.0,
                    stage TEXT NOT NULL DEFAULT '',
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_jobs_target ON agent_jobs (target_fingerprint, job_type);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_jobs_status ON agent_jobs (status);"))

            # -----------------------------------------------------------------
            # 6.5 Claim Feedback Table
            # -----------------------------------------------------------------
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_claim_feedback (
                    feedback_id VARCHAR(255) PRIMARY KEY,
                    claim_id VARCHAR(255) NOT NULL,
                    question TEXT,
                    statement TEXT NOT NULL,
                    user_rating INTEGER NOT NULL,
                    user_correction TEXT,
                    user_id VARCHAR(255),
                    created_at DOUBLE PRECISION NOT NULL
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS agent_claim_feedback (
                    feedback_id TEXT PRIMARY KEY,
                    claim_id TEXT NOT NULL,
                    question TEXT,
                    statement TEXT NOT NULL,
                    user_rating INTEGER NOT NULL,
                    user_correction TEXT,
                    user_id TEXT,
                    created_at REAL NOT NULL
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_claim_feedback_claim ON agent_claim_feedback (claim_id);"))

            # -----------------------------------------------------------------
            # 6.6 Chat History Tables
            # -----------------------------------------------------------------
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS chat_history_sessions (
                    session_id VARCHAR(255) PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at DOUBLE PRECISION NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS chat_history_sessions (
                    session_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS chat_history_turns (
                    turn_id SERIAL PRIMARY KEY,
                    session_id VARCHAR(255) NOT NULL,
                    question TEXT NOT NULL,
                    sql TEXT NOT NULL,
                    result_summary TEXT NOT NULL,
                    intent VARCHAR(64) NOT NULL,
                    timestamp DOUBLE PRECISION NOT NULL
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS chat_history_turns (
                    turn_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    sql TEXT NOT NULL,
                    result_summary TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    timestamp REAL NOT NULL
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_chat_turns_session ON chat_history_turns (session_id);"))

            # -----------------------------------------------------------------
            # 7. Authoritative Normalized Schema Catalog Tables
            # -----------------------------------------------------------------
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS catalog_database_connections (
                    connection_id VARCHAR(255) PRIMARY KEY,
                    database_name VARCHAR(255),
                    tenant_id VARCHAR(255),
                    dialect VARCHAR(64),
                    fingerprint VARCHAR(255) NOT NULL,
                    version VARCHAR(64),
                    last_introspected_at DOUBLE PRECISION NOT NULL,
                    last_profiled_at DOUBLE PRECISION
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS catalog_database_connections (
                    connection_id TEXT PRIMARY KEY,
                    database_name TEXT,
                    tenant_id TEXT,
                    dialect TEXT,
                    fingerprint TEXT NOT NULL,
                    version TEXT,
                    last_introspected_at REAL NOT NULL,
                    last_profiled_at REAL
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cat_conn_fp ON catalog_database_connections (fingerprint);"))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS catalog_schema_objects (
                    object_id VARCHAR(512) PRIMARY KEY,
                    fingerprint VARCHAR(255) NOT NULL,
                    schema_name VARCHAR(255),
                    object_name VARCHAR(255) NOT NULL,
                    object_type VARCHAR(64) NOT NULL DEFAULT 'table',
                    row_count_estimate BIGINT,
                    description TEXT,
                    status VARCHAR(32) NOT NULL DEFAULT 'active',
                    fk_degree INTEGER NOT NULL DEFAULT 0,
                    last_profiled_at DOUBLE PRECISION,
                    profile_status VARCHAR(32) NOT NULL DEFAULT 'unprofiled'
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS catalog_schema_objects (
                    object_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    schema_name TEXT,
                    object_name TEXT NOT NULL,
                    object_type TEXT NOT NULL DEFAULT 'table',
                    row_count_estimate INTEGER,
                    description TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    fk_degree INTEGER NOT NULL DEFAULT 0,
                    last_profiled_at REAL,
                    profile_status TEXT NOT NULL DEFAULT 'unprofiled'
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cat_obj_fp_name ON catalog_schema_objects (fingerprint, object_name);"))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS catalog_columns (
                    column_id VARCHAR(512) PRIMARY KEY,
                    object_id VARCHAR(512) NOT NULL,
                    fingerprint VARCHAR(255) NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    normalized_name VARCHAR(255),
                    data_type VARCHAR(128) NOT NULL,
                    nullable BOOLEAN NOT NULL DEFAULT TRUE,
                    primary_key BOOLEAN NOT NULL DEFAULT FALSE,
                    is_foreign_key BOOLEAN NOT NULL DEFAULT FALSE,
                    semantic_type VARCHAR(64),
                    description TEXT,
                    synonyms_json TEXT,
                    null_fraction DOUBLE PRECISION,
                    distinct_estimate BIGINT,
                    samples_json TEXT,
                    date_range TEXT
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS catalog_columns (
                    column_id TEXT PRIMARY KEY,
                    object_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    name TEXT NOT NULL,
                    normalized_name TEXT,
                    data_type TEXT NOT NULL,
                    nullable INTEGER NOT NULL DEFAULT 1,
                    primary_key INTEGER NOT NULL DEFAULT 0,
                    is_foreign_key INTEGER NOT NULL DEFAULT 0,
                    semantic_type TEXT,
                    description TEXT,
                    synonyms_json TEXT,
                    null_fraction REAL,
                    distinct_estimate INTEGER,
                    samples_json TEXT,
                    date_range TEXT
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cat_col_obj_fp ON catalog_columns (object_id, fingerprint);"))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS catalog_relationships (
                    relationship_id VARCHAR(512) PRIMARY KEY,
                    fingerprint VARCHAR(255) NOT NULL,
                    source_object VARCHAR(255) NOT NULL,
                    source_column VARCHAR(255) NOT NULL,
                    target_object VARCHAR(255) NOT NULL,
                    target_column VARCHAR(255) NOT NULL,
                    relationship_type VARCHAR(64) NOT NULL DEFAULT 'foreign_key',
                    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                    source VARCHAR(64) NOT NULL DEFAULT 'db_introspection'
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS catalog_relationships (
                    relationship_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    source_object TEXT NOT NULL,
                    source_column TEXT NOT NULL,
                    target_object TEXT NOT NULL,
                    target_column TEXT NOT NULL,
                    relationship_type TEXT NOT NULL DEFAULT 'foreign_key',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source TEXT NOT NULL DEFAULT 'db_introspection'
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cat_rel_fp ON catalog_relationships (fingerprint, source_object, target_object);"))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS catalog_index_stats (
                    index_id VARCHAR(512) PRIMARY KEY,
                    object_id VARCHAR(512) NOT NULL,
                    fingerprint VARCHAR(255) NOT NULL,
                    index_name VARCHAR(255) NOT NULL,
                    columns_json TEXT,
                    uniqueness BOOLEAN NOT NULL DEFAULT FALSE,
                    selectivity_hints TEXT
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS catalog_index_stats (
                    index_id TEXT PRIMARY KEY,
                    object_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    index_name TEXT NOT NULL,
                    columns_json TEXT,
                    uniqueness INTEGER NOT NULL DEFAULT 0,
                    selectivity_hints TEXT
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cat_ix_obj ON catalog_index_stats (object_id, fingerprint);"))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS catalog_alias_terms (
                    alias_id VARCHAR(512) PRIMARY KEY,
                    fingerprint VARCHAR(255) NOT NULL,
                    canonical_id VARCHAR(512) NOT NULL,
                    entity_type VARCHAR(64) NOT NULL DEFAULT 'table',
                    term VARCHAR(255) NOT NULL,
                    language VARCHAR(32) NOT NULL DEFAULT 'en',
                    source VARCHAR(64) NOT NULL DEFAULT 'llm_glossary',
                    confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS catalog_alias_terms (
                    alias_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    canonical_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL DEFAULT 'table',
                    term TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT 'en',
                    source TEXT NOT NULL DEFAULT 'llm_glossary',
                    confidence REAL NOT NULL DEFAULT 1.0
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cat_alias_fp_term ON catalog_alias_terms (fingerprint, term);"))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS catalog_versions (
                    version_id VARCHAR(255) PRIMARY KEY,
                    fingerprint VARCHAR(255) NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    change_timestamp DOUBLE PRECISION NOT NULL,
                    build_status VARCHAR(64) NOT NULL DEFAULT 'completed',
                    profile_freshness_status VARCHAR(64) NOT NULL DEFAULT 'unprofiled',
                    tables_count INTEGER NOT NULL DEFAULT 0,
                    columns_count INTEGER NOT NULL DEFAULT 0,
                    profiled_tables_count INTEGER NOT NULL DEFAULT 0,
                    last_introspected_at DOUBLE PRECISION NOT NULL DEFAULT 0.0,
                    last_profiled_at DOUBLE PRECISION,
                    job_id VARCHAR(255)
                );
            """ if not self.is_sqlite else """
                CREATE TABLE IF NOT EXISTS catalog_versions (
                    version_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    change_timestamp REAL NOT NULL,
                    build_status TEXT NOT NULL DEFAULT 'completed',
                    profile_freshness_status TEXT NOT NULL DEFAULT 'unprofiled',
                    tables_count INTEGER NOT NULL DEFAULT 0,
                    columns_count INTEGER NOT NULL DEFAULT 0,
                    profiled_tables_count INTEGER NOT NULL DEFAULT 0,
                    last_introspected_at REAL NOT NULL DEFAULT 0.0,
                    last_profiled_at REAL,
                    job_id TEXT
                );
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cat_ver_fp ON catalog_versions (fingerprint, version);"))

    # -------------------------------------------------------------------------
    # 1. Session Management
    # -------------------------------------------------------------------------

    def get_session_url(self, session_id: str) -> Optional[str]:
        """Fetch the database URL mapped to a session ID."""
        try:
            with self.engine.connect() as conn:
                res = conn.execute(
                    text("SELECT database_url FROM agent_sessions WHERE session_id = :s"),
                    {"s": session_id},
                ).scalar()
                return str(res) if res is not None else None
        except Exception as e:
            logger.warning("Error reading session from system store", error=str(e))
            return None

    def set_session_url(self, session_id: str, database_url: str) -> bool:
        """Store or update the database URL mapped to a session ID."""
        try:
            now = float(time.time())
            with self._lock, self.engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO agent_sessions (session_id, database_url, updated_at)
                        VALUES (:s, :u, :t)
                        ON CONFLICT (session_id) DO UPDATE SET
                            database_url = :u,
                            updated_at = :t
                    """),
                    {"s": session_id, "u": database_url, "t": now},
                )
                return True
        except Exception as e:
            logger.warning("Error saving session to system store", error=str(e))
            return False

    # -------------------------------------------------------------------------
    # 2. General Key-Value Cache with TTL
    # -------------------------------------------------------------------------

    def get_cache(self, key: str) -> Optional[str]:
        """Fetch value from cache if it exists and has not expired."""
        try:
            now = float(time.time())
            with self.engine.connect() as conn:
                row = conn.execute(
                    text("SELECT value, expires_at FROM agent_cache WHERE key = :k"),
                    {"k": key},
                ).fetchone()
                if not row:
                    return None

                val, expires_at = row[0], float(row[1])
                if now <= expires_at:
                    return str(val)

            # Cleanup expired key
            with self._lock, self.engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM agent_cache WHERE key = :k"),
                    {"k": key},
                )
            return None
        except Exception as e:
            logger.warning("Error reading from cache store", error=str(e))
            return None

    def set_cache(self, key: str, value: str, ttl_seconds: int) -> bool:
        """Write key-value with TTL to cache store."""
        try:
            expires_at = float(time.time() + ttl_seconds)
            with self._lock, self.engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO agent_cache (key, value, expires_at)
                        VALUES (:k, :v, :exp)
                        ON CONFLICT (key) DO UPDATE SET
                            value = :v,
                            expires_at = :exp
                    """),
                    {"k": key, "v": value, "exp": expires_at},
                )
                return True
        except Exception as e:
            logger.warning("Error writing to cache store", error=str(e))
            return False

    def clear_cache(self, prefix: Optional[str] = None) -> bool:
        """Clear all or matching cache entries."""
        try:
            with self._lock, self.engine.begin() as conn:
                if prefix:
                    conn.execute(
                        text("DELETE FROM agent_cache WHERE key LIKE :p"),
                        {"p": f"{prefix}%"},
                    )
                else:
                    conn.execute(text("DELETE FROM agent_cache"))
                return True
        except Exception as e:
            logger.warning("Error clearing cache store", error=str(e))
            return False

    # -------------------------------------------------------------------------
    # 3. Token-Bucket Rate Limiter
    # -------------------------------------------------------------------------

    def consume_rate_limit(self, client_key: str, capacity: int, window_seconds: float = 60.0) -> bool:
        """Atomic token bucket rate limiter in durable storage."""
        try:
            now = float(time.time())
            refill_rate = capacity / window_seconds
            with self._lock, self.engine.begin() as conn:
                row = conn.execute(
                    text("SELECT tokens, last_refill FROM agent_rate_limits WHERE ip_address = :ip"),
                    {"ip": client_key},
                ).fetchone()

                if not row:
                    # First request from this client
                    conn.execute(
                        text("INSERT INTO agent_rate_limits (ip_address, tokens, last_refill) VALUES (:ip, :tok, :refill)"),
                        {"ip": client_key, "tok": float(capacity - 1), "refill": now},
                    )
                    return True

                tokens, last_refill = float(row[0]), float(row[1])
                elapsed = now - last_refill
                tokens = min(float(capacity), tokens + elapsed * refill_rate)

                if tokens >= 1.0:
                    tokens -= 1.0
                    conn.execute(
                        text("UPDATE agent_rate_limits SET tokens = :tok, last_refill = :refill WHERE ip_address = :ip"),
                        {"tok": tokens, "refill": now, "ip": client_key},
                    )
                    return True
                else:
                    conn.execute(
                        text("UPDATE agent_rate_limits SET tokens = :tok, last_refill = :refill WHERE ip_address = :ip"),
                        {"tok": tokens, "refill": now, "ip": client_key},
                    )
                    return False
        except Exception as e:
            logger.warning("Error in rate limiter, failing open", error=str(e))
            return True

    # -------------------------------------------------------------------------
    # 4. Long-Term Memory (User Queries & Preferences)
    # -------------------------------------------------------------------------

    def get_memory(self, user_id: str, sub: str) -> Optional[Any]:
        """Fetch parsed JSON data from long-term memory."""
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text("SELECT data FROM agent_memory WHERE user_id = :u AND sub = :s"),
                    {"u": user_id, "s": sub},
                ).scalar()
                if row:
                    return json.loads(str(row))
                return None
        except Exception as e:
            logger.warning("Error reading from memory store", error=str(e))
            return None

    def set_memory(self, user_id: str, sub: str, data: Any) -> bool:
        """Save JSON data to long-term memory."""
        try:
            serialized = json.dumps(data)
            now = float(time.time())
            with self._lock, self.engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO agent_memory (user_id, sub, data, updated_at)
                        VALUES (:u, :s, :d, :t)
                        ON CONFLICT (user_id, sub) DO UPDATE SET
                            data = :d,
                            updated_at = :t
                    """),
                    {"u": user_id, "s": sub, "d": serialized, "t": now},
                )
                return True
        except Exception as e:
            logger.warning("Error saving to memory store", error=str(e))
            return False

    def delete_memory(self, user_id: str, sub: str) -> bool:
        """Delete specific sub-memory for a user."""
        try:
            with self._lock, self.engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM agent_memory WHERE user_id = :u AND sub = :s"),
                    {"u": user_id, "s": sub},
                )
                return True
        except Exception as e:
            logger.warning("Error deleting from memory store", error=str(e))
            return False

    # -------------------------------------------------------------------------
    # 4.5 Chat History Methods
    # -------------------------------------------------------------------------

    def get_chat_sessions(self) -> list[dict[str, Any]]:
        """Fetch all chat sessions ordered by updated_at descending."""
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT session_id, title, created_at, updated_at FROM chat_history_sessions ORDER BY updated_at DESC")
                ).fetchall()
                return [
                    {
                        "session_id": str(r[0]),
                        "title": str(r[1]),
                        "created_at": float(r[2]),
                        "updated_at": float(r[3]),
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning("Error fetching chat sessions", error=str(e))
            return []

    def get_chat_history(self, session_id: str) -> list[dict[str, Any]]:
        """Fetch all turns for a given session."""
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT question, sql, result_summary, intent, timestamp 
                        FROM chat_history_turns 
                        WHERE session_id = :s 
                        ORDER BY turn_id ASC
                    """),
                    {"s": session_id}
                ).fetchall()
                return [
                    {
                        "question": str(r[0]),
                        "sql": str(r[1]),
                        "result_summary": str(r[2]),
                        "intent": str(r[3]),
                        "timestamp": float(r[4])
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning("Error fetching chat history", error=str(e))
            return []

    def add_chat_turn(self, session_id: str, question: str, sql: str, result_summary: str, intent: str) -> bool:
        """Add a turn to a chat session, creating the session if it doesn't exist."""
        try:
            now = float(time.time())
            # Default title is the first question
            title = question[:50] + "..." if len(question) > 50 else question
            
            with self._lock, self.engine.begin() as conn:
                # Upsert session
                conn.execute(
                    text("""
                        INSERT INTO chat_history_sessions (session_id, title, created_at, updated_at)
                        VALUES (:s, :title, :now, :now)
                        ON CONFLICT (session_id) DO UPDATE SET
                            updated_at = :now
                    """),
                    {"s": session_id, "title": title, "now": now}
                )
                
                # Insert turn
                if self.is_sqlite:
                    conn.execute(
                        text("""
                            INSERT INTO chat_history_turns (session_id, question, sql, result_summary, intent, timestamp)
                            VALUES (:s, :q, :sql, :rs, :intent, :ts)
                        """),
                        {"s": session_id, "q": question, "sql": sql, "rs": result_summary, "intent": intent, "ts": now}
                    )
                else:
                    conn.execute(
                        text("""
                            INSERT INTO chat_history_turns (session_id, question, sql, result_summary, intent, timestamp)
                            VALUES (:s, :q, :sql, :rs, :intent, :ts)
                        """),
                        {"s": session_id, "q": question, "sql": sql, "rs": result_summary, "intent": intent, "ts": now}
                    )
                return True
        except Exception as e:
            logger.warning("Error adding chat turn", error=str(e))
            return False

    def delete_chat_session(self, session_id: str) -> bool:
        """Delete a chat session and all its turns."""
        try:
            with self._lock, self.engine.begin() as conn:
                conn.execute(text("DELETE FROM chat_history_turns WHERE session_id = :s"), {"s": session_id})
                conn.execute(text("DELETE FROM chat_history_sessions WHERE session_id = :s"), {"s": session_id})
                return True
        except Exception as e:
            logger.warning("Error deleting chat session", error=str(e))
            return False

    # -------------------------------------------------------------------------
    # 5. Schema Service Cache & Catalog Progress
    # -------------------------------------------------------------------------

    def get_schema_cache(self, db_hash: str) -> Optional[dict[str, Any]]:
        """Fetch cached schema data for a database fingerprint."""
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text("SELECT data FROM agent_schema_cache WHERE db_hash = :h"),
                    {"h": db_hash},
                ).scalar()
                if row:
                    return json.loads(str(row))
                return None
        except Exception as e:
            logger.warning("Error reading schema cache from system store", error=str(e))
            return None

    def set_schema_cache(self, db_hash: str, data: dict[str, Any]) -> bool:
        """Persist schema cache entry for a database fingerprint."""
        try:
            serialized = json.dumps(data)
            now = float(time.time())
            with self._lock, self.engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO agent_schema_cache (db_hash, data, updated_at)
                        VALUES (:h, :d, :t)
                        ON CONFLICT (db_hash) DO UPDATE SET
                            data = :d,
                            updated_at = :t
                    """),
                    {"h": db_hash, "d": serialized, "t": now},
                )
                return True
        except Exception as e:
            logger.warning("Error saving schema cache to system store", error=str(e))
            return False

    def clear_schema_cache(self, db_hash_prefix: Optional[str] = None) -> bool:
        """Clear all or matching schema cache entries."""
        try:
            with self._lock, self.engine.begin() as conn:
                if db_hash_prefix:
                    conn.execute(
                        text("DELETE FROM agent_schema_cache WHERE db_hash LIKE :p"),
                        {"p": f"{db_hash_prefix}%"},
                    )
                else:
                    conn.execute(text("DELETE FROM agent_schema_cache"))
                return True
        except Exception as e:
            logger.warning("Error clearing schema cache in system store", error=str(e))
            return False

    def get_catalog_progress(self, db_hash: str) -> dict[str, Any]:
        """Fetch catalog build progress dict."""
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text("SELECT progress FROM agent_catalog_progress WHERE db_hash = :h"),
                    {"h": db_hash},
                ).scalar()
                if row:
                    return json.loads(str(row))
                return {}
        except Exception as e:
            logger.warning("Error reading catalog progress from system store", error=str(e))
            return {}

    def set_catalog_progress(self, db_hash: str, progress: dict[str, Any]) -> bool:
        """Save catalog build progress dict."""
        try:
            serialized = json.dumps(progress)
            now = float(time.time())
            with self._lock, self.engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO agent_catalog_progress (db_hash, progress, updated_at)
                        VALUES (:h, :p, :t)
                        ON CONFLICT (db_hash) DO UPDATE SET
                            progress = :p,
                            updated_at = :t
                    """),
                    {"h": db_hash, "p": serialized, "t": now},
                )
                return True
        except Exception as e:
            logger.warning("Error saving catalog progress to system store", error=str(e))
            return False

    # -------------------------------------------------------------------------
    # 6. Durable Background Jobs (Onboarding / Profiling Queue)
    # -------------------------------------------------------------------------

    def create_job(
        self,
        job_id: str,
        job_type: str,
        target_fingerprint: str,
        database_url: str,
        status: str = "pending",
        stage: str = "init",
    ) -> dict[str, Any]:
        """Create a durable background job record."""
        now = float(time.time())
        try:
            with self._lock, self.engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO agent_jobs (
                            job_id, job_type, target_fingerprint, database_url,
                            status, progress_percent, stage, error, created_at, updated_at, completed_at
                        ) VALUES (
                            :jid, :jtype, :fp, :url, :status, 0.0, :stage, NULL, :now, :now, NULL
                        )
                    """),
                    {
                        "jid": job_id, "jtype": job_type, "fp": target_fingerprint,
                        "url": database_url, "status": status, "stage": stage, "now": now,
                    },
                )
            return {
                "job_id": job_id,
                "job_type": job_type,
                "target_fingerprint": target_fingerprint,
                "database_url": database_url,
                "status": status,
                "progress_percent": 0.0,
                "stage": stage,
                "error": None,
                "created_at": now,
                "updated_at": now,
                "completed_at": None,
            }
        except Exception as e:
            logger.warning("Error creating job in system store", error=str(e))
            raise

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        """Fetch a job by job_id."""
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT job_id, job_type, target_fingerprint, database_url,
                               status, progress_percent, stage, error, created_at, updated_at, completed_at
                        FROM agent_jobs WHERE job_id = :jid
                    """),
                    {"jid": job_id},
                ).fetchone()
                if not row:
                    return None
                return {
                    "job_id": str(row[0]),
                    "job_type": str(row[1]),
                    "target_fingerprint": str(row[2]),
                    "database_url": str(row[3]),
                    "status": str(row[4]),
                    "progress_percent": float(row[5]),
                    "stage": str(row[6]),
                    "error": str(row[7]) if row[7] is not None else None,
                    "created_at": float(row[8]),
                    "updated_at": float(row[9]),
                    "completed_at": float(row[10]) if row[10] is not None else None,
                }
        except Exception as e:
            logger.warning("Error reading job from system store", error=str(e))
            return None

    def get_active_job_for_fingerprint(
        self,
        target_fingerprint: str,
        job_type: str = "onboarding",
    ) -> Optional[dict[str, Any]]:
        """Fetch any pending or currently running job for the given target fingerprint."""
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT job_id, job_type, target_fingerprint, database_url,
                               status, progress_percent, stage, error, created_at, updated_at, completed_at
                        FROM agent_jobs
                        WHERE target_fingerprint = :fp AND job_type = :jtype AND status IN ('pending', 'running')
                        ORDER BY created_at DESC LIMIT 1
                    """),
                    {"fp": target_fingerprint, "jtype": job_type},
                ).fetchone()
                if not row:
                    return None
                return {
                    "job_id": str(row[0]),
                    "job_type": str(row[1]),
                    "target_fingerprint": str(row[2]),
                    "database_url": str(row[3]),
                    "status": str(row[4]),
                    "progress_percent": float(row[5]),
                    "stage": str(row[6]),
                    "error": str(row[7]) if row[7] is not None else None,
                    "created_at": float(row[8]),
                    "updated_at": float(row[9]),
                    "completed_at": float(row[10]) if row[10] is not None else None,
                }
        except Exception as e:
            logger.warning("Error reading active job for fingerprint from system store", error=str(e))
            return None

    def update_job_status(
        self,
        job_id: str,
        status: str,
        progress_percent: float = 0.0,
        stage: str = "",
        error: Optional[str] = None,
    ) -> bool:
        """Update job status, progress, stage, and error in durable store."""
        now = float(time.time())
        completed_at = now if status in ("completed", "failed") else None
        try:
            with self._lock, self.engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE agent_jobs
                        SET status = :status,
                            progress_percent = :progress,
                            stage = :stage,
                            error = :error,
                            updated_at = :now,
                            completed_at = CASE WHEN :comp IS NOT NULL THEN :comp ELSE completed_at END
                        WHERE job_id = :jid
                    """),
                    {
                        "jid": job_id,
                        "status": status,
                        "progress": float(progress_percent),
                        "stage": stage,
                        "error": error,
                        "now": now,
                        "comp": completed_at,
                    },
                )
                return True
        except Exception as e:
            logger.warning("Error updating job in system store", error=str(e))
            return False

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        """List most recent background jobs."""
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT job_id, job_type, target_fingerprint, database_url,
                               status, progress_percent, stage, error, created_at, updated_at, completed_at
                        FROM agent_jobs ORDER BY created_at DESC LIMIT :lim
                    """),
                    {"lim": limit},
                ).fetchall()
                return [
                    {
                        "job_id": str(r[0]),
                        "job_type": str(r[1]),
                        "target_fingerprint": str(r[2]),
                        "database_url": str(r[3]),
                        "status": str(r[4]),
                        "progress_percent": float(r[5]),
                        "stage": str(r[6]),
                        "error": str(r[7]) if r[7] is not None else None,
                        "created_at": float(r[8]),
                        "updated_at": float(r[9]),
                        "completed_at": float(r[10]) if r[10] is not None else None,
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning("Error listing jobs from system store", error=str(e))
            return []

    # -------------------------------------------------------------------------
    # 6.5 Claim Feedback Management
    # -------------------------------------------------------------------------

    def record_claim_feedback(
        self,
        claim_id: str,
        statement: str,
        user_rating: int,
        question: str = "",
        user_correction: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Record user feedback / correction on a specific answer claim."""
        import uuid
        feedback_id = f"fb_{uuid.uuid4().hex[:12]}"
        now = float(time.time())
        try:
            with self._lock, self.engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO agent_claim_feedback
                        (feedback_id, claim_id, question, statement, user_rating, user_correction, user_id, created_at)
                        VALUES (:fid, :cid, :q, :stmt, :rating, :corr, :uid, :now)
                    """),
                    {
                        "fid": feedback_id,
                        "cid": claim_id,
                        "q": question,
                        "stmt": statement,
                        "rating": int(user_rating),
                        "corr": user_correction,
                        "uid": user_id,
                        "now": now,
                    },
                )
            return {
                "feedback_id": feedback_id,
                "claim_id": claim_id,
                "user_rating": user_rating,
                "statement": statement,
                "user_correction": user_correction,
                "created_at": now,
            }
        except Exception as e:
            logger.warning("Error recording claim feedback in system store", error=str(e))
            return {}

    def get_claim_feedback(self, claim_id: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        """Retrieve recorded feedback for claims."""
        try:
            with self.engine.connect() as conn:
                if claim_id:
                    stmt = text("SELECT feedback_id, claim_id, question, statement, user_rating, user_correction, user_id, created_at FROM agent_claim_feedback WHERE claim_id = :cid ORDER BY created_at DESC LIMIT :lim")
                    rows = conn.execute(stmt, {"cid": claim_id, "lim": limit}).fetchall()
                else:
                    stmt = text("SELECT feedback_id, claim_id, question, statement, user_rating, user_correction, user_id, created_at FROM agent_claim_feedback ORDER BY created_at DESC LIMIT :lim")
                    rows = conn.execute(stmt, {"lim": limit}).fetchall()
                return [
                    {
                        "feedback_id": str(r[0]),
                        "claim_id": str(r[1]),
                        "question": str(r[2]) if r[2] else "",
                        "statement": str(r[3]),
                        "user_rating": int(r[4]),
                        "user_correction": str(r[5]) if r[5] else None,
                        "user_id": str(r[6]) if r[6] else None,
                        "created_at": float(r[7]),
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning("Error retrieving claim feedback from system store", error=str(e))
            return []

    # -------------------------------------------------------------------------
    # 7. Authoritative Normalized Schema Catalog Management
    # -------------------------------------------------------------------------

    def save_catalog_connection(self, record: Any) -> bool:
        """Persist DatabaseConnectionRecord to authoritative catalog storage."""
        try:
            with self._lock, self.engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO catalog_database_connections (
                            connection_id, database_name, tenant_id, dialect,
                            fingerprint, version, last_introspected_at, last_profiled_at
                        ) VALUES (
                            :cid, :dbname, :tenant, :dialect, :fp, :ver, :intro, :prof
                        )
                        ON CONFLICT (connection_id) DO UPDATE SET
                            database_name = :dbname,
                            tenant_id = :tenant,
                            dialect = :dialect,
                            fingerprint = :fp,
                            version = :ver,
                            last_introspected_at = :intro,
                            last_profiled_at = :prof
                    """),
                    {
                        "cid": record.connection_id,
                        "dbname": record.database_name,
                        "tenant": record.tenant_id,
                        "dialect": record.dialect,
                        "fp": record.fingerprint,
                        "ver": record.version,
                        "intro": float(record.last_introspected_at),
                        "prof": float(record.last_profiled_at) if record.last_profiled_at is not None else None,
                    },
                )
            return True
        except Exception as e:
            logger.warning("Error saving catalog connection to system store", error=str(e))
            return False

    def get_catalog_connection(self, fingerprint: str) -> Optional[Any]:
        """Fetch DatabaseConnectionRecord for fingerprint."""
        from app.models.schema_catalog.models import DatabaseConnectionRecord
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT connection_id, database_name, tenant_id, dialect,
                               fingerprint, version, last_introspected_at, last_profiled_at
                        FROM catalog_database_connections WHERE fingerprint = :fp
                        LIMIT 1
                    """),
                    {"fp": fingerprint},
                ).fetchone()
                if not row:
                    return None
                return DatabaseConnectionRecord(
                    connection_id=str(row[0]),
                    database_name=str(row[1]) if row[1] else "Database",
                    tenant_id=str(row[2]) if row[2] else None,
                    dialect=str(row[3]) if row[3] else "sql",
                    fingerprint=str(row[4]),
                    version=str(row[5]) if row[5] else "1.0",
                    last_introspected_at=float(row[6]),
                    last_profiled_at=float(row[7]) if row[7] is not None else None,
                )
        except Exception as e:
            logger.warning("Error getting catalog connection from system store", error=str(e))
            return None

    def save_schema_objects(self, objects: list[Any]) -> bool:
        """Persist list of SchemaObjectRecords independently."""
        if not objects:
            return True
        try:
            with self._lock, self.engine.begin() as conn:
                for o in objects:
                    conn.execute(
                        text("""
                            INSERT INTO catalog_schema_objects (
                                object_id, fingerprint, schema_name, object_name,
                                object_type, row_count_estimate, description, status,
                                fk_degree, last_profiled_at, profile_status
                            ) VALUES (
                                :oid, :fp, :sname, :oname, :otype, :rc, :desc, :status, :deg, :prof_at, :prof_stat
                            )
                            ON CONFLICT (object_id) DO UPDATE SET
                                fingerprint = :fp,
                                schema_name = :sname,
                                object_name = :oname,
                                object_type = :otype,
                                row_count_estimate = :rc,
                                description = :desc,
                                status = :status,
                                fk_degree = :deg,
                                last_profiled_at = :prof_at,
                                profile_status = :prof_stat
                        """),
                        {
                            "oid": o.object_id,
                            "fp": o.fingerprint,
                            "sname": o.schema_name,
                            "oname": o.object_name,
                            "otype": o.object_type,
                            "rc": int(o.row_count_estimate) if o.row_count_estimate is not None else None,
                            "desc": o.description,
                            "status": o.status,
                            "deg": int(o.fk_degree),
                            "prof_at": float(o.last_profiled_at) if getattr(o, "last_profiled_at", None) is not None else None,
                            "prof_stat": getattr(o, "profile_status", "unprofiled"),
                        },
                    )
            return True
        except Exception as e:
            logger.warning("Error saving schema objects to system store", error=str(e))
            return False

    def get_schema_objects(self, fingerprint: str, table_names: Optional[list[str]] = None) -> list[Any]:
        """Fetch SchemaObjectRecords for a fingerprint, optionally filtered by table names."""
        from app.models.schema_catalog.models import SchemaObjectRecord
        try:
            with self.engine.connect() as conn:
                if table_names:
                    # Parameterized IN clause
                    names_params = {f"t_{i}": name for i, name in enumerate(table_names)}
                    in_clause = ", ".join(f":t_{i}" for i in range(len(table_names)))
                    query = text(f"""
                        SELECT object_id, fingerprint, schema_name, object_name,
                               object_type, row_count_estimate, description, status,
                               fk_degree, last_profiled_at, profile_status
                        FROM catalog_schema_objects
                        WHERE fingerprint = :fp AND object_name IN ({in_clause})
                    """)
                    params = {"fp": fingerprint, **names_params}
                else:
                    query = text("""
                        SELECT object_id, fingerprint, schema_name, object_name,
                               object_type, row_count_estimate, description, status,
                               fk_degree, last_profiled_at, profile_status
                        FROM catalog_schema_objects
                        WHERE fingerprint = :fp
                    """)
                    params = {"fp": fingerprint}

                rows = conn.execute(query, params).fetchall()
                return [
                    SchemaObjectRecord(
                        object_id=str(r[0]),
                        fingerprint=str(r[1]),
                        schema_name=str(r[2]) if r[2] else "public",
                        object_name=str(r[3]),
                        object_type=str(r[4]) if r[4] else "table",
                        row_count_estimate=int(r[5]) if r[5] is not None else None,
                        description=str(r[6]) if r[6] is not None else None,
                        status=str(r[7]) if r[7] else "active",
                        fk_degree=int(r[8]) if r[8] is not None else 0,
                        last_profiled_at=float(r[9]) if r[9] is not None else None,
                        profile_status=str(r[10]) if r[10] else "unprofiled",
                    )
                    for r in rows
                ]
        except Exception as e:
            logger.warning("Error getting schema objects from system store", error=str(e))
            return []

    def save_columns(self, columns: list[Any]) -> bool:
        """Persist list of ColumnRecords independently."""
        if not columns:
            return True
        try:
            with self._lock, self.engine.begin() as conn:
                for c in columns:
                    conn.execute(
                        text("""
                            INSERT INTO catalog_columns (
                                column_id, object_id, fingerprint, name, normalized_name,
                                data_type, nullable, primary_key, is_foreign_key,
                                semantic_type, description, synonyms_json,
                                null_fraction, distinct_estimate, samples_json, date_range
                            ) VALUES (
                                :cid, :oid, :fp, :name, :nname, :dtype, :null, :pk, :fk,
                                :stype, :desc, :syns, :null_frac, :dist, :samples, :drange
                            )
                            ON CONFLICT (column_id) DO UPDATE SET
                                object_id = :oid,
                                fingerprint = :fp,
                                name = :name,
                                normalized_name = :nname,
                                data_type = :dtype,
                                nullable = :null,
                                primary_key = :pk,
                                is_foreign_key = :fk,
                                semantic_type = :stype,
                                description = :desc,
                                synonyms_json = :syns,
                                null_fraction = :null_frac,
                                distinct_estimate = :dist,
                                samples_json = :samples,
                                date_range = :drange
                        """),
                        {
                            "cid": c.column_id,
                            "oid": c.object_id,
                            "fp": c.fingerprint,
                            "name": c.name,
                            "nname": getattr(c, "normalized_name", c.name),
                            "dtype": c.data_type,
                            "null": bool(c.nullable),
                            "pk": bool(c.primary_key),
                            "fk": bool(c.is_foreign_key),
                            "stype": c.semantic_type,
                            "desc": c.description,
                            "syns": json.dumps(c.synonyms) if c.synonyms else "[]",
                            "null_frac": float(c.null_fraction) if c.null_fraction is not None else None,
                            "dist": int(c.distinct_estimate) if c.distinct_estimate is not None else None,
                            "samples": json.dumps(c.samples) if c.samples else "[]",
                            "drange": c.date_range,
                        },
                    )
            return True
        except Exception as e:
            logger.warning("Error saving columns to system store", error=str(e))
            return False

    def get_columns_for_objects(self, fingerprint: str, object_ids: Optional[list[str]] = None) -> list[Any]:
        """Fetch ColumnRecords for objects in a fingerprint."""
        from app.models.schema_catalog.models import ColumnRecord
        try:
            with self.engine.connect() as conn:
                if object_ids:
                    id_params = {f"o_{i}": oid for i, oid in enumerate(object_ids)}
                    in_clause = ", ".join(f":o_{i}" for i in range(len(object_ids)))
                    query = text(f"""
                        SELECT column_id, object_id, fingerprint, name, normalized_name,
                               data_type, nullable, primary_key, is_foreign_key,
                               semantic_type, description, synonyms_json,
                               null_fraction, distinct_estimate, samples_json, date_range
                        FROM catalog_columns
                        WHERE fingerprint = :fp AND object_id IN ({in_clause})
                    """)
                    params = {"fp": fingerprint, **id_params}
                else:
                    query = text("""
                        SELECT column_id, object_id, fingerprint, name, normalized_name,
                               data_type, nullable, primary_key, is_foreign_key,
                               semantic_type, description, synonyms_json,
                               null_fraction, distinct_estimate, samples_json, date_range
                        FROM catalog_columns
                        WHERE fingerprint = :fp
                    """)
                    params = {"fp": fingerprint}

                rows = conn.execute(query, params).fetchall()
                return [
                    ColumnRecord(
                        column_id=str(r[0]),
                        object_id=str(r[1]),
                        fingerprint=str(r[2]),
                        name=str(r[3]),
                        normalized_name=str(r[4]) if r[4] else str(r[3]),
                        data_type=str(r[5]),
                        nullable=bool(r[6]),
                        primary_key=bool(r[7]),
                        is_foreign_key=bool(r[8]),
                        semantic_type=str(r[9]) if r[9] is not None else None,
                        description=str(r[10]) if r[10] is not None else None,
                        synonyms=json.loads(str(r[11])) if r[11] else [],
                        null_fraction=float(r[12]) if r[12] is not None else None,
                        distinct_estimate=int(r[13]) if r[13] is not None else None,
                        samples=json.loads(str(r[14])) if r[14] else [],
                        date_range=str(r[15]) if r[15] is not None else None,
                    )
                    for r in rows
                ]
        except Exception as e:
            logger.warning("Error getting columns from system store", error=str(e))
            return []

    def save_relationships(self, relationships: list[Any]) -> bool:
        """Persist list of RelationshipRecords independently."""
        if not relationships:
            return True
        try:
            with self._lock, self.engine.begin() as conn:
                for r in relationships:
                    conn.execute(
                        text("""
                            INSERT INTO catalog_relationships (
                                relationship_id, fingerprint, source_object, source_column,
                                target_object, target_column, relationship_type, confidence, source
                            ) VALUES (
                                :rid, :fp, :so, :sc, :to, :tc, :rtype, :conf, :src
                            )
                            ON CONFLICT (relationship_id) DO UPDATE SET
                                fingerprint = :fp,
                                source_object = :so,
                                source_column = :sc,
                                target_object = :to,
                                target_column = :tc,
                                relationship_type = :rtype,
                                confidence = :conf,
                                source = :src
                        """),
                        {
                            "rid": r.relationship_id,
                            "fp": r.fingerprint,
                            "so": r.source_object,
                            "sc": r.source_column,
                            "to": r.target_object,
                            "tc": r.target_column,
                            "rtype": r.relationship_type,
                            "conf": float(r.confidence),
                            "src": r.source,
                        },
                    )
            return True
        except Exception as e:
            logger.warning("Error saving relationships to system store", error=str(e))
            return False

    def get_relationships(self, fingerprint: str) -> list[Any]:
        """Fetch all RelationshipRecords for fingerprint."""
        from app.models.schema_catalog.models import RelationshipRecord
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT relationship_id, fingerprint, source_object, source_column,
                               target_object, target_column, relationship_type, confidence, source
                        FROM catalog_relationships WHERE fingerprint = :fp
                    """),
                    {"fp": fingerprint},
                ).fetchall()
                return [
                    RelationshipRecord(
                        relationship_id=str(r[0]),
                        fingerprint=str(r[1]),
                        source_object=str(r[2]),
                        source_column=str(r[3]),
                        target_object=str(r[4]),
                        target_column=str(r[5]),
                        relationship_type=str(r[6]),
                        confidence=float(r[7]),
                        source=str(r[8]),
                    )
                    for r in rows
                ]
        except Exception as e:
            logger.warning("Error getting relationships from system store", error=str(e))
            return []

    def save_indexes(self, indexes: list[Any]) -> bool:
        """Persist list of IndexStatsRecords independently."""
        if not indexes:
            return True
        try:
            with self._lock, self.engine.begin() as conn:
                for ix in indexes:
                    conn.execute(
                        text("""
                            INSERT INTO catalog_index_stats (
                                index_id, object_id, fingerprint, index_name,
                                columns_json, uniqueness, selectivity_hints
                            ) VALUES (
                                :iid, :oid, :fp, :iname, :cols, :uniq, :hints
                            )
                            ON CONFLICT (index_id) DO UPDATE SET
                                object_id = :oid,
                                fingerprint = :fp,
                                index_name = :iname,
                                columns_json = :cols,
                                uniqueness = :uniq,
                                selectivity_hints = :hints
                        """),
                        {
                            "iid": ix.index_id,
                            "oid": ix.object_id,
                            "fp": ix.fingerprint,
                            "iname": ix.index_name,
                            "cols": json.dumps(ix.columns) if ix.columns else "[]",
                            "uniq": bool(ix.uniqueness),
                            "hints": ix.selectivity_hints,
                        },
                    )
            return True
        except Exception as e:
            logger.warning("Error saving indexes to system store", error=str(e))
            return False

    def get_indexes(self, fingerprint: str) -> list[Any]:
        """Fetch IndexStatsRecords for fingerprint."""
        from app.models.schema_catalog.models import IndexStatsRecord
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT index_id, object_id, fingerprint, index_name,
                               columns_json, uniqueness, selectivity_hints
                        FROM catalog_index_stats WHERE fingerprint = :fp
                    """),
                    {"fp": fingerprint},
                ).fetchall()
                return [
                    IndexStatsRecord(
                        index_id=str(r[0]),
                        object_id=str(r[1]),
                        fingerprint=str(r[2]),
                        index_name=str(r[3]),
                        columns=json.loads(str(r[4])) if r[4] else [],
                        uniqueness=bool(r[5]),
                        selectivity_hints=str(r[6]) if r[6] is not None else None,
                    )
                    for r in rows
                ]
        except Exception as e:
            logger.warning("Error getting indexes from system store", error=str(e))
            return []

    def save_aliases(self, aliases: list[Any]) -> bool:
        """Persist list of AliasTermRecords independently."""
        if not aliases:
            return True
        try:
            with self._lock, self.engine.begin() as conn:
                for a in aliases:
                    conn.execute(
                        text("""
                            INSERT INTO catalog_alias_terms (
                                alias_id, fingerprint, canonical_id, entity_type,
                                term, language, source, confidence
                            ) VALUES (
                                :aid, :fp, :cid, :etype, :term, :lang, :src, :conf
                            )
                            ON CONFLICT (alias_id) DO UPDATE SET
                                fingerprint = :fp,
                                canonical_id = :cid,
                                entity_type = :etype,
                                term = :term,
                                language = :lang,
                                source = :src,
                                confidence = :conf
                        """),
                        {
                            "aid": a.alias_id,
                            "fp": a.fingerprint,
                            "cid": a.canonical_id,
                            "etype": a.entity_type,
                            "term": a.term,
                            "lang": getattr(a, "language", "en"),
                            "src": a.source,
                            "conf": float(a.confidence),
                        },
                    )
            return True
        except Exception as e:
            logger.warning("Error saving aliases to system store", error=str(e))
            return False

    def get_aliases(self, fingerprint: str) -> list[Any]:
        """Fetch AliasTermRecords for fingerprint."""
        from app.models.schema_catalog.models import AliasTermRecord
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT alias_id, fingerprint, canonical_id, entity_type,
                               term, language, source, confidence
                        FROM catalog_alias_terms WHERE fingerprint = :fp
                    """),
                    {"fp": fingerprint},
                ).fetchall()
                return [
                    AliasTermRecord(
                        alias_id=str(r[0]),
                        fingerprint=str(r[1]),
                        canonical_id=str(r[2]),
                        entity_type=str(r[3]),
                        term=str(r[4]),
                        language=str(r[5]) if r[5] else "en",
                        source=str(r[6]),
                        confidence=float(r[7]),
                    )
                    for r in rows
                ]
        except Exception as e:
            logger.warning("Error getting aliases from system store", error=str(e))
            return []

    def save_catalog_version(self, version: Any) -> bool:
        """Record a new catalog version in durable history."""
        try:
            with self._lock, self.engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO catalog_versions (
                            version_id, fingerprint, version, change_timestamp,
                            build_status, profile_freshness_status, tables_count,
                            columns_count, profiled_tables_count, last_introspected_at,
                            last_profiled_at, job_id
                        ) VALUES (
                            :vid, :fp, :ver, :ts, :bstat, :fstat, :tcnt, :ccnt, :pcnt, :intro, :prof, :jid
                        )
                        ON CONFLICT (version_id) DO UPDATE SET
                            fingerprint = :fp,
                            version = :ver,
                            change_timestamp = :ts,
                            build_status = :bstat,
                            profile_freshness_status = :fstat,
                            tables_count = :tcnt,
                            columns_count = :ccnt,
                            profiled_tables_count = :pcnt,
                            last_introspected_at = :intro,
                            last_profiled_at = :prof,
                            job_id = :jid
                    """),
                    {
                        "vid": version.version_id,
                        "fp": version.fingerprint,
                        "ver": int(version.version),
                        "ts": float(version.change_timestamp),
                        "bstat": version.build_status,
                        "fstat": getattr(version, "profile_freshness_status", "unprofiled"),
                        "tcnt": int(getattr(version, "tables_count", 0)),
                        "ccnt": int(getattr(version, "columns_count", 0)),
                        "pcnt": int(getattr(version, "profiled_tables_count", 0)),
                        "intro": float(getattr(version, "last_introspected_at", 0.0)),
                        "prof": float(version.last_profiled_at) if getattr(version, "last_profiled_at", None) is not None else None,
                        "jid": version.job_id,
                    },
                )
            return True
        except Exception as e:
            logger.warning("Error saving catalog version to system store", error=str(e))
            return False

    def get_latest_catalog_version(self, fingerprint: str) -> Optional[Any]:
        """Fetch the newest CatalogVersionRecord for fingerprint."""
        from app.models.schema_catalog.models import CatalogVersionRecord
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text("""
                        SELECT version_id, fingerprint, version, change_timestamp,
                               build_status, profile_freshness_status, tables_count,
                               columns_count, profiled_tables_count, last_introspected_at,
                               last_profiled_at, job_id
                        FROM catalog_versions WHERE fingerprint = :fp
                        ORDER BY version DESC LIMIT 1
                    """),
                    {"fp": fingerprint},
                ).fetchone()
                if not row:
                    return None
                return CatalogVersionRecord(
                    version_id=str(row[0]),
                    fingerprint=str(row[1]),
                    version=int(row[2]),
                    change_timestamp=float(row[3]),
                    build_status=str(row[4]),
                    profile_freshness_status=str(row[5]) if row[5] else "unprofiled",
                    tables_count=int(row[6]) if row[6] is not None else 0,
                    columns_count=int(row[7]) if row[7] is not None else 0,
                    profiled_tables_count=int(row[8]) if row[8] is not None else 0,
                    last_introspected_at=float(row[9]) if row[9] is not None else 0.0,
                    last_profiled_at=float(row[10]) if row[10] is not None else None,
                    job_id=str(row[11]) if row[11] else None,
                )
        except Exception as e:
            logger.warning("Error getting latest catalog version from system store", error=str(e))
            return None

    def update_table_profile_stats(
        self,
        fingerprint: str,
        table_name: str,
        row_count: Optional[int] = None,
        column_stats: Optional[dict[str, Any]] = None,
        profiled_at: Optional[float] = None,
    ) -> bool:
        """
        Independently update table-level row count and column-level sample statistics
        in authoritative normalized persistent storage without rewriting the entire catalog.
        """
        now = profiled_at if profiled_at is not None else float(time.time())
        try:
            with self._lock, self.engine.begin() as conn:
                # 1. Update SchemaObject row count & profile timestamp
                conn.execute(
                    text("""
                        UPDATE catalog_schema_objects
                        SET row_count_estimate = :rc,
                            last_profiled_at = :ts,
                            profile_status = 'profiled'
                        WHERE fingerprint = :fp AND object_name = :tname
                    """),
                    {"rc": int(row_count) if row_count is not None else None, "ts": now, "fp": fingerprint, "tname": table_name},
                )

                # 2. Update Column statistics independently
                if column_stats:
                    for col_name, stats in column_stats.items():
                        samples_json = json.dumps(stats.get("samples", [])) if "samples" in stats else None
                        date_range = stats.get("date_range")
                        null_fraction = stats.get("null_fraction")
                        distinct_est = stats.get("distinct_estimate")

                        conn.execute(
                            text("""
                                UPDATE catalog_columns
                                SET samples_json = COALESCE(:samples, samples_json),
                                    date_range = COALESCE(:drange, date_range),
                                    null_fraction = COALESCE(:nfrac, null_fraction),
                                    distinct_estimate = COALESCE(:dest, distinct_estimate)
                                WHERE fingerprint = :fp AND name = :cname
                                  AND object_id IN (
                                      SELECT object_id FROM catalog_schema_objects
                                      WHERE fingerprint = :fp AND object_name = :tname
                                  )
                            """),
                            {
                                "samples": samples_json,
                                "drange": date_range,
                                "nfrac": float(null_fraction) if null_fraction is not None else None,
                                "dest": int(distinct_est) if distinct_est is not None else None,
                                "fp": fingerprint,
                                "cname": col_name,
                                "tname": table_name,
                            },
                        )
            return True
        except Exception as e:
            logger.warning("Error updating table profile stats in system store", error=str(e), table=table_name)
            return False

    def save_normalized_catalog(self, catalog: Any) -> bool:
        """Persist full SchemaCatalog into authoritative normalized entities."""
        try:
            records = catalog.to_normalized_records()
            if records.get("connection"):
                self.save_catalog_connection(records["connection"][0])
            self.save_schema_objects(records.get("objects", []))
            self.save_columns(records.get("columns", []))
            self.save_relationships(records.get("relationships", []))
            self.save_indexes(records.get("indexes", []))
            self.save_aliases(records.get("aliases", []))
            if records.get("version"):
                self.save_catalog_version(records["version"][0])
            return True
        except Exception as e:
            logger.warning("Error saving normalized catalog to system store", error=str(e))
            return False

    def load_normalized_catalog(self, fingerprint: str) -> Optional[Any]:
        """Load SchemaCatalog from authoritative normalized persistent entities in SystemStore."""
        from app.models.schema_catalog.models import SchemaCatalog, DatabaseConnectionRecord
        try:
            objects = self.get_schema_objects(fingerprint)
            if not objects:
                return None

            connection = self.get_catalog_connection(fingerprint) or DatabaseConnectionRecord(
                connection_id=f"conn_{fingerprint[:12]}",
                fingerprint=fingerprint,
            )
            columns = self.get_columns_for_objects(fingerprint)
            relationships = self.get_relationships(fingerprint)
            indexes = self.get_indexes(fingerprint)
            aliases = self.get_aliases(fingerprint)
            version = self.get_latest_catalog_version(fingerprint)

            return SchemaCatalog.from_normalized_records(
                connection=connection,
                objects=objects,
                columns=columns,
                relationships=relationships,
                indexes=indexes,
                aliases=aliases,
                version=version,
                built_at=connection.last_introspected_at,
            )
        except Exception as e:
            logger.warning("Error loading normalized catalog from system store", error=str(e))
            return None

    def load_table_subset(self, fingerprint: str, table_names: list[str]) -> dict[str, Any]:
        """Selectively load only requested candidate tables and their columns in O(K) time."""
        from app.models.schema_catalog.models import TableProfile, ColumnProfile
        if not table_names:
            return {}
        try:
            objects = self.get_schema_objects(fingerprint, table_names=table_names)
            if not objects:
                return {}

            obj_ids = [o.object_id for o in objects]
            columns = self.get_columns_for_objects(fingerprint, object_ids=obj_ids)
            aliases = self.get_aliases(fingerprint)

            cols_by_obj: dict[str, list[ColumnProfile]] = {}
            for c in columns:
                cols_by_obj.setdefault(c.object_id, []).append(
                    ColumnProfile(
                        name=c.name,
                        type=c.data_type,
                        nullable=c.nullable,
                        primary_key=c.primary_key,
                        is_foreign_key=c.is_foreign_key,
                        samples=c.samples,
                        date_range=c.date_range,
                        distinct_count=c.distinct_estimate,
                        null_fraction=c.null_fraction,
                        description=c.description,
                        synonyms=c.synonyms,
                    )
                )

            results: dict[str, TableProfile] = {}
            for obj in objects:
                t_cols = cols_by_obj.get(obj.object_id, [])
                synonyms = [
                    a.term for a in aliases
                    if a.entity_type == "table" and (a.canonical_id == obj.object_id or a.canonical_id.endswith(f":{obj.object_name}"))
                ]
                is_prof = obj.row_count_estimate is not None or obj.profile_status == "profiled"
                results[obj.object_name] = TableProfile(
                    name=obj.object_name,
                    columns=t_cols,
                    primary_key=[c.name for c in t_cols if c.primary_key],
                    foreign_keys=[],
                    indexes=[],
                    row_count=obj.row_count_estimate,
                    fk_degree=obj.fk_degree,
                    profiled=is_prof,
                    last_profiled_at=obj.last_profiled_at,
                    profile_status=obj.profile_status or ("profiled" if is_prof else "unprofiled"),
                    description=obj.description,
                    synonyms=synonyms,
                )
            return results
        except Exception as e:
            logger.warning("Error loading table subset from system store", error=str(e), tables=table_names)
            return {}


# Singleton global instance
system_store = SystemStore()


