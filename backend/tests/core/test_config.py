import pytest
from pydantic import ValidationError
from app.core.config.settings import Settings

def test_settings_default_instantiation():
    """Test that settings instantiate with valid defaults."""
    settings = Settings(environment="development")
    assert settings.project_name == "AI Database Analyst Agent"
    assert settings.environment == "development"
    assert settings.secret_key == "database-analyst-agent-default-secure-key-2026"

def test_settings_lowercase_providers():
    """Test validator for lowercase providers."""
    settings = Settings(llm_provider="OPENROUTER", embedding_provider="OPENAI_COMPATIBLE")
    assert settings.llm_provider == "openrouter"
    assert settings.embedding_provider == "openai_compatible"

def test_settings_production_secret_key_validation():
    """Test that production environment requires a strong custom secret key."""
    # Should fail with default key
    with pytest.raises(ValidationError, match="CRITICAL SECURITY CONFIGURATION"):
        Settings(environment="production")
        
    # Should fail with short key
    with pytest.raises(ValidationError, match="must be at least 32 characters long"):
        Settings(environment="production", secret_key="shortkey")
        
    # Should succeed with valid long key
    settings = Settings(environment="production", secret_key="a" * 32)
    assert settings.secret_key == "a" * 32

def test_extra_masked_column_patterns_parsing():
    """Test parsing of CSV string for masked columns."""
    settings = Settings(extra_masked_column_patterns="ssn, credit_card ,  phone")
    assert settings.extra_masked_column_patterns == ["ssn", "credit_card", "phone"]
    
    settings_list = Settings(extra_masked_column_patterns=["ssn", "credit_card"])
    assert settings_list.extra_masked_column_patterns == ["ssn", "credit_card"]
