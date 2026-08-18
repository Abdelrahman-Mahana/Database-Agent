import pytest
from app.database.db import set_database_url, get_engine, current_session_id

def test_engine_caching_per_session():
    """Ensure engine caching respects different sessions (Multi-Tenant)."""
    # Tenant 1 connects to db1
    token1 = current_session_id.set("tenant_1")
    engine1 = set_database_url("sqlite:///tenant_1.db")
    cached_engine1 = get_engine()
    
    assert str(engine1.url) == "sqlite:///tenant_1.db"
    assert engine1 is cached_engine1
    
    # Tenant 2 connects to db2 in a different context
    token2 = current_session_id.set("tenant_2")
    engine2 = set_database_url("sqlite:///tenant_2.db")
    cached_engine2 = get_engine()
    
    assert str(engine2.url) == "sqlite:///tenant_2.db"
    assert engine2 is cached_engine2
    assert engine1 is not engine2
    
    # Restore Tenant 1 context and verify engine
    current_session_id.reset(token2)
    current_session_id.set("tenant_1")
    assert get_engine() is engine1
