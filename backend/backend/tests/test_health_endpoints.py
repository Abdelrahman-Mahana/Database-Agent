import asyncio

from fastapi import HTTPException

from app.api import health
from app.config.settings import settings


def test_health_is_local_and_does_not_construct_an_llm_client(monkeypatch):
    """Frequent /health polling must never touch an LLM provider client."""
    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", "configured-key")

    def fail_if_called():
        raise AssertionError("/health must not construct or call an LLM client")

    monkeypatch.setattr(health, "get_llm_client", fail_if_called)
    response = asyncio.run(health.health_check())

    assert response.status == "healthy"
    assert response.llm_configured is True
    assert response.llm_latency_ms is None


def test_readiness_only_validates_local_provider_configuration(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", "")

    try:
        asyncio.run(health.readiness_check())
    except HTTPException as exc:
        assert exc.status_code == 503
    else:
        raise AssertionError("unconfigured provider must not be ready")


def test_dependencies_uses_non_generating_provider_probe(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "openrouter")
    monkeypatch.setattr(settings, "openrouter_api_key", "configured-key")

    class ProbeClient:
        async def health_check(self):
            return True, 12.5

    monkeypatch.setattr(health, "get_llm_client", lambda: ProbeClient())
    response = asyncio.run(health.dependencies_check())

    assert response["status"] == "healthy"
    assert response["llm"]["reachable"] is True
    assert response["llm"]["latency_ms"] == 12.5
