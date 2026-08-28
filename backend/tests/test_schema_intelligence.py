import pytest
from app.agent.schema_grounding.schema_intelligence import compute_structural_schema_fingerprint, SchemaIntelligenceCache

def test_compute_structural_schema_fingerprint_deterministic():
    schema1 = {
        "users": {
            "columns": [{"name": "id", "type": "int"}, {"name": "name", "type": "text"}],
            "primary_key": ["id"],
        },
        "orders": {
            "columns": [{"name": "id", "type": "int"}, {"name": "user_id", "type": "int"}],
            "foreign_keys": [
                {"constrained_columns": ["user_id"], "referred_table": "users", "referred_columns": ["id"]}
            ]
        }
    }

    # Same logical schema, different dictionary order
    schema2 = {
        "orders": {
            "foreign_keys": [
                {"referred_columns": ["id"], "referred_table": "users", "constrained_columns": ["user_id"]}
            ],
            "columns": [{"name": "user_id", "type": "int"}, {"name": "id", "type": "int"}],
        },
        "users": {
            "primary_key": ["id"],
            "columns": [{"name": "name", "type": "text"}, {"name": "id", "type": "int"}],
        }
    }

    fp1 = compute_structural_schema_fingerprint(schema1)
    fp2 = compute_structural_schema_fingerprint(schema2)
    
    assert fp1 == fp2
    assert fp1.startswith("custom_schema_")

def test_schema_intelligence_cache():
    SchemaIntelligenceCache.clear()
    schema = {"users": {"columns": []}}
    
    # Miss
    bundle1, hit1, _, _ = SchemaIntelligenceCache.get_or_build("hash123", schema)
    assert not hit1
    assert bundle1.fingerprint == "hash123"
    
    # Hit
    bundle2, hit2, _, _ = SchemaIntelligenceCache.get_or_build("hash123", schema)
    assert hit2
    assert bundle1 is bundle2
    
    # Clear
    SchemaIntelligenceCache.clear("hash123")
    bundle3, hit3, _, _ = SchemaIntelligenceCache.get_or_build("hash123", schema)
    assert not hit3
    assert bundle1 is not bundle3
