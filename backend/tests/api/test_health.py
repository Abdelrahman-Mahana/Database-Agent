import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_liveness_check():
    """Test the /health/live endpoint."""
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}

def test_health_check_endpoint(monkeypatch):
    """Test the general /health endpoint."""
    from app.core.config.settings import settings
    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", "fake_key")
    
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["llm_provider"] == "openrouter"
    assert data["llm_configured"] is True

def test_readiness_check_not_configured(monkeypatch):
    """Test readiness when API key is missing."""
    from app.core.config.settings import settings
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "not_ready"

def test_readiness_check_configured(monkeypatch):
    """Test readiness when configured correctly."""
    from app.core.config.settings import settings
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "test_key")
    
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
