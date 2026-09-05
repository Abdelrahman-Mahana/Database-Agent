import pytest
from app.services.database.context import (
    compute_db_fingerprint,
    DatabaseContext,
    DatabaseContextManager,
)

def test_compute_db_fingerprint():
    """Test fingerprint generation."""
    fp1 = compute_db_fingerprint("sqlite:///test.db")
    fp2 = compute_db_fingerprint("sqlite:///test.db")
    assert fp1 == fp2
    
    fp3 = compute_db_fingerprint("postgresql://user:pass@host/db")
    assert fp1 != fp3

def test_database_context_manager():
    """Test the LRU cache behavior of DatabaseContextManager."""
    manager = DatabaseContextManager(capacity=2)
    
    ctx1 = DatabaseContext(fingerprint="fp1", url="url1")
    ctx2 = DatabaseContext(fingerprint="fp2", url="url2")
    ctx3 = DatabaseContext(fingerprint="fp3", url="url3")
    
    manager.set("fp1", ctx1)
    manager.set("fp2", ctx2)
    
    assert manager.get("fp1") == ctx1
    assert manager.count() == 2
    
    # Adding third should evict fp2, since fp1 was just accessed
    manager.set("fp3", ctx3)
    assert manager.get("fp2") is None
    assert manager.get("fp1") == ctx1
    assert manager.get("fp3") == ctx3
    assert manager.count() == 2

def test_database_context_methods():
    """Test DatabaseContext properties and methods."""
    ctx = DatabaseContext(fingerprint="fp", url="url", database_name="TestDB")
    
    # Add dummy schema
    ctx.schema = {
        "users": {"columns": [{"name": "id", "type": "int"}]},
        "posts": {"columns": [{"name": "id", "type": "int"}, {"name": "title", "type": "str"}]}
    }
    
    assert ctx.compact_summary is not None
    assert "TestDB" in ctx.compact_summary
    assert "users" in ctx.compact_summary
    
    # Test semantic versioning
    v1 = ctx.get_semantic_version()
    assert v1 is not None
    
    # Check expiration logic
    assert not ctx.is_expired(ttl=3600)
