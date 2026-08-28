import os
import pytest
from app.core.config.settings import Settings

def test_settings_load_defaults():
    """Ensure pydantic-settings loads default configurations properly."""
    settings = Settings(secret_key="test_secret", database_url="sqlite:///test.db")
    assert settings.project_name == "AI Database Analyst Agent"
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.database_url == "sqlite:///test.db"

def test_settings_validation_failure():
    """Ensure pydantic-settings validates configuration types."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(sampling_threshold="invalid_not_an_int")
