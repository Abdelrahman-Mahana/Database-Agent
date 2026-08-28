import pytest
from app.core.security.data_masking import mask_sensitive_columns, MASK_VALUE

def test_mask_sensitive_columns():
    rows = [
        {"id": 1, "name": "Alice", "password_hash": "bcrypt123", "ssn": "000-00-0000", "public_profile": "hello"},
        {"id": 2, "name": "Bob", "password_hash": "bcrypt456", "ssn": "111-11-1111", "public_profile": "world"}
    ]

    masked_rows, sensitive_cols = mask_sensitive_columns(rows)
    
    assert set(sensitive_cols) == {"password_hash", "ssn"}
    
    # Assert original dicts were not mutated
    assert rows[0]["password_hash"] == "bcrypt123"
    
    # Assert new dicts are masked
    assert masked_rows[0]["password_hash"] == MASK_VALUE
    assert masked_rows[0]["ssn"] == MASK_VALUE
    assert masked_rows[0]["name"] == "Alice" # untouched
    assert masked_rows[0]["public_profile"] == "hello" # untouched

    def test_mask_sensitive_columns_with_extra_patterns():
        rows = [
            {"id": 1, "internal_project_name": "Apollo", "revenue": 5000}
        ]
        
        # By default, internal_project_name is NOT masked
        masked_rows, sensitive_cols = mask_sensitive_columns(rows)
        assert not sensitive_cols
        assert masked_rows[0]["internal_project_name"] == "Apollo"
        
        # With extra pattern
        masked_rows, sensitive_cols = mask_sensitive_columns(rows, extra_patterns=["internal"])
        assert "internal_project_name" in sensitive_cols
        assert masked_rows[0]["internal_project_name"] == MASK_VALUE

def test_mask_sensitive_columns_empty():
    assert mask_sensitive_columns([]) == ([], [])
