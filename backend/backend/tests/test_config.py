import os
import pytest
from app.config.settings import Settings

def test_settings_load_defaults():
    """Ensure pydantic-settings loads default configurations properly."""
    settings = Settings(secret_key="test_secret", database_url="sqlite:///test.db")
    assert settings.project_name == "AI Database Analyst Agent"
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.database_url == "sqlite:///test.db"

def test_settings_validation_failure(monkeypatch):
    """Ensure pydantic-settings requires a secret_key."""
    from pydantic import ValidationError
    
    # Remove SECRET_KEY from the environment and .env if it exists
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("secret_key", raising=False)
    
    with pytest.raises(ValidationError):
        # Missing secret_key should raise ValidationError
        # Override _env_file to prevent it from reading from .env
        Settings(_env_file=None, database_url="sqlite:///test.db")
