"""Supabase client (Deprecated / No-op).

All state, session, and cache operations have been migrated to the local
embedded SQLite system store (app.database.system_store).
"""
from typing import Any, Optional


def get_supabase_client() -> Optional[Any]:
    """Deprecated stub: always returns None as Supabase is replaced by system_store."""
    return None
