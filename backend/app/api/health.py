"""Health check API route."""
import asyncio

from fastapi import APIRouter

from app.llm.model import get_llm_client
from app.schemas.chat import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Fast, non-blocking container health check endpoint."""
    llm_ok = False
    latency_ms = None
    pricing = {"prompt": 0.0, "completion": 0.0}

    client = None
    try:
        client = get_llm_client()
        # Fast non-blocking LLM ping with 1.0s timeout max
        llm_ok, latency = await asyncio.wait_for(client.health_check(), timeout=1.0)
        if llm_ok:
            latency_ms = latency
            try:
                pricing = await client.get_pricing()
            except Exception:
                pass
    except Exception:
        llm_ok = False

    return HealthResponse(
        status="healthy",
        llm_available=llm_ok,
        llm_provider=getattr(client, "provider", "unknown") if client else "unknown",
        ollama_available=(getattr(client, "provider", "unknown") == "ollama" and llm_ok) if client else False,
        model=getattr(client, "model", "unknown") if client else "unknown",
        llm_latency_ms=latency_ms,
        pricing=pricing,
    )
