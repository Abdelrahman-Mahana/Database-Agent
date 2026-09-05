import pytest
from app.services.database.db import (
    normalize_database_url,
    EngineCache,
    TTLCache,
    reset_database_layer,
    current_session_id,
    get_engine,
    get_session_url,
    set_database_url
)
from app.core.config.settings import settings

def test_normalize_database_url():
    """Test standardizing database URLs."""
    assert normalize_database_url("postgres://user:pass@host/db") == "postgresql+psycopg2://user:pass@host/db"
    assert normalize_database_url("postgresql://user:pass@host/db") == "postgresql+psycopg2://user:pass@host/db"
    assert normalize_database_url("mysql://user:pass@host/db") == "mysql+pymysql://user:pass@host/db"
    assert normalize_database_url("sqlite:///data.db") == "sqlite:///data.db"

def test_engine_cache():
    """Test the EngineCache LRU logic."""
    cache = EngineCache(capacity=2)
    class MockEngine:
        def __init__(self, name):
            self.name = name
            self.disposed = False
        def dispose(self):
            self.disposed = True
            
    engine1 = MockEngine("engine1")
    engine2 = MockEngine("engine2")
    engine3 = MockEngine("engine3")

    cache.set("url1", engine1, "sm1")
    cache.set("url2", engine2, "sm2")
    
    # Access url1 to make url2 the least recently used
    assert cache.get_engine("url1") == engine1
    
    # Push url3, url2 should be evicted
    cache.set("url3", engine3, "sm3")
    
    assert cache.get_engine("url2") is None
    assert engine2.disposed is True
    assert cache.get_engine("url1") == engine1
    assert cache.get_engine("url3") == engine3

def test_get_engine_creates_sqlite(tmp_path):
    """Test getting an engine automatically creates and returns an SQLAlchemy Engine."""
    db_file = tmp_path / "test.db"
    url = f"sqlite:///{db_file}"
    
    # Set the current session
    token = current_session_id.set("test_session_id")
    try:
        set_database_url(url)
        engine = get_engine()
        assert engine is not None
        assert str(engine.url) == url
    finally:
        current_session_id.reset(token)
        reset_database_layer()
