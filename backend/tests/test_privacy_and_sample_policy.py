"""Tests for Enterprise Schema Sample Privacy Policy and PII Scrubbing Engine."""
import pytest
from unittest.mock import patch, MagicMock

from app.core.security.privacy_policy import (
    is_safe_semantic_sample_column,
    PIIValueSanitizer,
    DENIED_SUBSTRING_PATTERNS,
    ALLOWED_SAMPLE_CATEGORICAL_PATTERNS,
)
from app.agent.schema_grounding.schema_pruner import SchemaPruner
from app.core.config.settings import settings


def test_sensitive_columns_never_sampled():
    """Verify that all PII, credential, financial, medical, and contact columns are rejected from sampling."""
    sensitive_columns = [
        "email", "email_address", "user_email",
        "phone", "mobile_no", "telephone",
        "password", "password_hash", "passwd", "secret_key", "auth_token", "jwt",
        "ssn", "social_security_number", "national_id", "passport_no", "tax_id",
        "salary", "annual_wage", "credit_card", "card_number", "cvv", "bank_account",
        "first_name", "last_name", "full_name", "customer_name", "patient_name",
        "dob", "date_of_birth", "birth_date",
        "address", "street_address", "zip_code", "postal_code",
        "diagnosis", "prescription", "medical_notes",
        "note", "comments", "body_content", "payload_json", "user_bio",
        "ip_address", "device_id",
    ]

    for col in sensitive_columns:
        assert not is_safe_semantic_sample_column(col), f"Column '{col}' should NOT be considered safe for sampling!"


def test_short_column_names_do_not_bypass_privacy():
    """Verify that legacy len(name) <= 15 loophole is removed and arbitrary short columns are rejected."""
    short_sensitive = ["name", "usr", "bio", "pin", "addr", "hash", "salt", "ssn", "id", "guid"]
    for col in short_sensitive:
        assert not is_safe_semantic_sample_column(col), f"Short column '{col}' must not bypass privacy check!"


def test_safe_categorical_columns_are_allowed():
    """Verify that legitimate low-cardinality categorical columns pass the allowlist."""
    safe_columns = [
        "status", "order_status", "payment_status", "invoice_state",
        "product_type", "account_type", "user_role",
        "category", "item_category", "department",
        "subscription_tier", "priority", "plan",
        "country", "state", "city", "region", "currency", "iso_code",
        "shipping_method", "payment_method", "channel", "brand",
    ]

    for col in safe_columns:
        assert is_safe_semantic_sample_column(col), f"Categorical column '{col}' should be safe for sampling."


def test_pii_value_sanitizer_detects_all_pii_patterns():
    """Verify that PIIValueSanitizer catches emails, phones, credit cards, SSNs, IPs, JWTs, and UUIDs."""
    pii_samples = [
        "john.doe@example.com",
        "contact@company.org",
        "4532-1234-5678-9012",
        "4111111111111111",
        "123-45-6789",
        "+1 (555) 234-5678",
        "+44 20 7946 0958",
        "192.168.1.1",
        "10.0.0.254",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
        "550e8400-e29b-41d4-a716-446655440000",
    ]

    for sample in pii_samples:
        assert PIIValueSanitizer.contains_pii(sample), f"PII string '{sample}' was NOT detected as PII!"
        assert PIIValueSanitizer.sanitize_sample(sample) is None, f"PII string '{sample}' should be scrubbed to None!"

    # Safe categorical values should pass
    safe_samples = ["Active", "Pending", "CANCELLED", "USD", "EUR", "VIP", "Retail", "Credit Card"]
    for safe in safe_samples:
        assert not PIIValueSanitizer.contains_pii(safe), f"Safe sample '{safe}' was falsely flagged as PII!"
        assert PIIValueSanitizer.sanitize_sample(safe) == safe


def test_schema_pruner_filters_sensitive_column_samples():
    """Verify that SchemaPruner never includes samples for sensitive columns even if present in raw schema."""
    pruner = SchemaPruner()
    schema = {
        "users": {
            "columns": [
                {"name": "id", "type": "INTEGER"},
                {"name": "status", "type": "VARCHAR(20)", "samples": ["active", "suspended"]},
                {"name": "email", "type": "VARCHAR(100)", "samples": ["user@test.com", "admin@corp.com"]},
                {"name": "salary", "type": "FLOAT", "samples": [75000.0, 92000.0]},
                {"name": "role", "type": "VARCHAR(20)", "samples": ["admin", "editor"]},
            ],
            "primary_key": ["id"],
            "foreign_keys": [],
        }
    }

    lines = pruner._format_lines(
        tables_to_format=["users"],
        schema=schema,
        include_samples=True,
    )
    schema_text = "\n".join(lines)

    # Allowed categorical column samples must be included
    assert "status:VARCHAR(20)" in schema_text
    assert "e.g.'active'" in schema_text
    assert "role:VARCHAR(20)" in schema_text
    assert "e.g.'admin'" in schema_text

    # Sensitive columns must NOT have samples included
    assert "user@test.com" not in schema_text
    assert "admin@corp.com" not in schema_text
    assert "75000" not in schema_text


def test_schema_pruner_respects_enable_schema_samples_false():
    """Verify that setting enable_schema_samples=False completely removes all sample values from prompts."""
    pruner = SchemaPruner()
    schema = {
        "orders": {
            "columns": [
                {"name": "order_id", "type": "INTEGER"},
                {"name": "order_status", "type": "VARCHAR(20)", "samples": ["shipped", "delivered"]},
            ],
            "primary_key": ["order_id"],
            "foreign_keys": [],
        }
    }

    with patch("app.core.config.settings.settings.enable_schema_samples", False):
        lines = pruner._format_lines(
            tables_to_format=["orders"],
            schema=schema,
            include_samples=True,
        )
        schema_text = "\n".join(lines)
        assert "e.g." not in schema_text
        assert "shipped" not in schema_text


def test_schema_pruner_respects_strict_privacy_mode():
    """Verify that setting strict_privacy_mode=True completely blocks all samples from prompts."""
    pruner = SchemaPruner()
    schema = {
        "orders": {
            "columns": [
                {"name": "order_id", "type": "INTEGER"},
                {"name": "order_status", "type": "VARCHAR(20)", "samples": ["shipped", "delivered"]},
            ],
            "primary_key": ["order_id"],
            "foreign_keys": [],
        }
    }

    with patch("app.core.config.settings.settings.strict_privacy_mode", True):
        lines = pruner._format_lines(
            tables_to_format=["orders"],
            schema=schema,
            include_samples=True,
        )
        schema_text = "\n".join(lines)
        assert "e.g." not in schema_text
        assert "shipped" not in schema_text
