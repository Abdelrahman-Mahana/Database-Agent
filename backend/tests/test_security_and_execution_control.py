import pytest
from app.utils.helpers import validate_sql
from app.services.sql_service import is_safe_semantic_sample_column
from app.core.security.data_masking import mask_sensitive_columns


def test_validator_rejects_multi_statements():
    """Verify that multi-statement queries are strictly rejected by the AST validator."""
    res = validate_sql("SELECT * FROM users; DROP TABLE users;")
    assert res["valid"] is False
    assert "Multiple SQL statements" in res["reason"]


def test_validator_blocks_dangerous_functions():
    """Verify that file access and shell execution functions are blocked."""
    res1 = validate_sql("SELECT pg_read_file('/etc/passwd')")
    assert res1["valid"] is False
    assert "Forbidden administrative or file-access function" in res1["reason"]

    res2 = validate_sql("SELECT load_file('/var/lib/mysql-files/secret.txt')")
    assert res2["valid"] is False
    assert "Forbidden administrative or file-access function" in res2["reason"]


def test_validator_blocks_system_catalog_tables():
    """Verify that queries against sensitive system credential tables are blocked."""
    res1 = validate_sql("SELECT * FROM pg_shadow")
    assert res1["valid"] is False
    assert "restricted" in res1["reason"]

    res2 = validate_sql("SELECT * FROM mysql.user")
    assert res2["valid"] is False
    assert "restricted" in res2["reason"]


def test_safe_semantic_sample_column_allowlist():
    """Verify that safe categorical columns are allowed for profiling while PII/secrets are excluded."""
    # Denied PII and secrets
    assert is_safe_semantic_sample_column("password_hash") is False
    assert is_safe_semantic_sample_column("user_email") is False
    assert is_safe_semantic_sample_column("ssn_number") is False
    assert is_safe_semantic_sample_column("credit_card_token") is False
    assert is_safe_semantic_sample_column("customer_notes_and_comments") is False

    # Allowed safe categorical columns
    assert is_safe_semantic_sample_column("order_status") is True
    assert is_safe_semantic_sample_column("account_type") is True
    assert is_safe_semantic_sample_column("country_code") is True
    assert is_safe_semantic_sample_column("priority_tier") is True


def test_mask_sensitive_columns_redacts_credentials():
    """Verify that sensitive columns are redacted before model context exposure."""
    raw_rows = [
        {"user_id": 1, "username": "alice", "api_key": "sk-secret-12345", "password_hash": "hash999"},
        {"user_id": 2, "username": "bob", "api_key": "sk-secret-67890", "password_hash": "hash888"},
    ]

    masked_rows, masked_cols = mask_sensitive_columns(raw_rows)
    assert "api_key" in masked_cols
    assert "password_hash" in masked_cols
    assert masked_rows[0]["api_key"] == "***MASKED***"
    assert masked_rows[0]["password_hash"] == "***MASKED***"
    assert masked_rows[0]["username"] == "alice"  # Non-sensitive preserved
