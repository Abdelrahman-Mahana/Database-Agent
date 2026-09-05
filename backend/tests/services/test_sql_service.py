import pytest
from app.services.sql_service import SchemaCacheEntry, SchemaService
from app.core.config.settings import settings

def test_schema_cache_entry_expiration():
    """Test SchemaCacheEntry TTL and fingerprint logic."""
    import time
    entry = SchemaCacheEntry(
        schema={"table": {}},
        schema_text="schema text",
        fingerprint="fp1",
        timestamp=time.time() - 100,
    )
    
    # Should expire if fingerprint mismatch
    assert entry.is_expired(ttl=1000, current_fingerprint="fp2") is True
    
    # Should expire if TTL exceeded
    assert entry.is_expired(ttl=50, current_fingerprint="fp1") is True
    
    # Should not expire if fingerprint matches and TTL not exceeded
    assert entry.is_expired(ttl=200, current_fingerprint="fp1") is False
    
    # Should not expire if TTL is 0 (infinite)
    assert entry.is_expired(ttl=0, current_fingerprint="fp1") is False

def test_schema_cache_entry_serialization():
    """Test to_dict and from_dict for SchemaCacheEntry."""
    entry = SchemaCacheEntry(
        schema={"table": {}},
        schema_text="schema text",
        fingerprint="fp1",
        timestamp=100.0,
        recommended_questions=[{"title": "Q"}],
        explorer_data={"nodes": []}
    )
    
    data = entry.to_dict()
    assert data["fingerprint"] == "fp1"
    
    entry2 = SchemaCacheEntry.from_dict(data)
    assert entry2.fingerprint == "fp1"
    assert entry2.schema == {"table": {}}
    assert entry2.recommended_questions == [{"title": "Q"}]

def test_schema_service_initialization():
    """Test basic initialization of SchemaService."""
    service = SchemaService(bind_engine=None)
    assert service.ttl == settings.schema_cache_ttl
