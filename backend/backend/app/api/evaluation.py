"""Evaluation API routes.

Exposes the AI Evaluation Framework (app.evaluation) which scores every
chat request for confidence/quality and keeps a rolling in-memory
telemetry buffer. Wired into /chat via app.api.chat.
"""
from fastapi import APIRouter, HTTPException

from app.evaluation import EvaluationTelemetry

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.get("/history")
async def get_evaluation_history(limit: int = 50):
    """Return the most recent evaluation results (newest first)."""
    history = EvaluationTelemetry.get_history()
    ordered = list(reversed(history))[: max(1, min(limit, 100))]
    return {"count": len(ordered), "results": [r.model_dump() for r in ordered]}


@router.get("/stats")
async def get_evaluation_stats():
    """Return aggregate quality/confidence/cost stats over the buffered history."""
    history = EvaluationTelemetry.get_history()
    if not history:
        raise HTTPException(status_code=404, detail="No evaluation data recorded yet")

    n = len(history)
    avg_quality = round(sum(r.quality_score for r in history) / n, 2)
    avg_confidence = round(sum(r.confidence_score for r in history) / n, 3)
    avg_latency_ms = round(sum(r.stage_latency.total_ms for r in history) / n, 1)
    total_cost = round(sum(r.token_usage.estimated_cost_usd for r in history), 6)
    success_rate = round(
        sum(1 for r in history if r.metrics.sql_execution_success) / n * 100, 1
    )

    return {
        "sample_size": n,
        "avg_quality_score": avg_quality,
        "avg_confidence_score": avg_confidence,
        "avg_latency_ms": avg_latency_ms,
        "sql_success_rate_pct": success_rate,
        "total_estimated_cost_usd": total_cost,
    }


@router.delete("/history")
async def clear_evaluation_history():
    """Clear the in-memory evaluation telemetry buffer."""
    EvaluationTelemetry.clear_history()
    return {"status": "cleared"}
