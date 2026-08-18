"""Local, readiness, and dependency health endpoints.

None of the liveness or readiness endpoints makes an LLM generation request.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from app.config.settings import settings
from app.llm.model import get_llm_client
from app.schemas.chat import HealthResponse

router = APIRouter(tags=["health"])


def _provider_metadata() -> dict[str, str | bool]:
    """Return provider configuration without constructing a network client."""
    provider = settings.llm_provider.lower()
    config = {
        "ollama": (settings.ollama_model, settings.ollama_base_url, True),
        "openrouter": (settings.openrouter_model, settings.openrouter_base_url, bool(settings.openrouter_api_key)),
        "groq": (settings.groq_model, settings.groq_base_url, bool(settings.groq_api_key)),
        "openai": (settings.openai_model, settings.openai_base_url, bool(settings.openai_api_key)),
    }
    model, base_url, configured = config.get(provider, ("unknown", "", False))
    return {"provider": provider, "model": model, "base_url": base_url, "configured": configured}


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Compatibility health check: local-only and safe for frequent polling."""
    metadata = _provider_metadata()
    configured = bool(metadata["configured"])
    return HealthResponse(
        status="healthy",
        # Legacy field: it now means configured, not remotely verified.
        llm_available=configured,
        llm_configured=configured,
        llm_provider=str(metadata["provider"]),
        ollama_available=(metadata["provider"] == "ollama" and configured),
        model=str(metadata["model"]),
        llm_latency_ms=None,
        pricing=None,
    )


@router.get("/health/live")
async def liveness_check():
    """Process liveness only; never checks configuration or dependencies."""
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness_check():
    """Readiness based on local configuration only; no network or LLM call."""
    metadata = _provider_metadata()
    if not metadata["configured"]:
        raise HTTPException(
            status_code=503,
            detail={"status": "not_ready", "reason": "LLM provider is not configured", **metadata},
        )
    return {"status": "ready", **metadata}


@router.get("/health/dependencies")
async def dependencies_check():
    """Probe provider connectivity without generating tokens or sending prompts."""
    metadata = _provider_metadata()
    if not metadata["configured"]:
        return {"status": "degraded", "llm": {**metadata, "reachable": False}}
    try:
        client = get_llm_client()
        reachable, latency_ms = await asyncio.wait_for(client.health_check(), timeout=3.0)
    except Exception:
        reachable, latency_ms = False, None
    return {
        "status": "healthy" if reachable else "degraded",
        "llm": {**metadata, "reachable": reachable, "latency_ms": latency_ms if reachable else None},
    }
