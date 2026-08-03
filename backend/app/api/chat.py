"""Chat API routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.agents.analyst_agent import AnalystAgent
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.memory import memory_manager
from app.utils.token_tracker import reset_token_usage, get_current_token_usage
from app.utils.cost_dashboard import cost_dashboard
from app.core.config import settings
from app.llm.model import get_llm_client
from app.evaluation import AgentEvaluator

router = APIRouter(prefix="/chat", tags=["chat"])
agent = AnalystAgent()
evaluator = AgentEvaluator()


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    """Process a natural language question and return an analyst report."""
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    reset_token_usage()
    result = await agent.ask(request.message, db, session_id=request.session_id)
    usage = get_current_token_usage()
    if usage["prompt_tokens"] == 0 and usage["completion_tokens"] == 0:
        usage["prompt_tokens"] = max(10, len(request.message) // 4)
        resp_text = str(result.get("report") or result.get("answer") or result.get("sql") or "")
        usage["completion_tokens"] = max(15, len(resp_text) // 4)
    result["prompt_tokens"] = usage["prompt_tokens"]
    result["completion_tokens"] = usage["completion_tokens"]
    result["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]

    # Phase 8: record usage for the cost dashboard (best-effort — never let
    # tracking failures affect the actual response to the user).
    if settings.enable_cost_dashboard:
        try:
            model_name = getattr(get_llm_client(), "model", "unknown")
            cost_dashboard.record(
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                model=model_name,
                session_id=request.session_id,
                analysis_type=result.get("analysis_type"),
            )
        except Exception:
            pass

    # Score this request with the AI Evaluation Framework (best-effort —
    # never let evaluation failures affect the actual response to the user).
    # Results are queryable via GET /evaluation/history and /evaluation/stats.
    try:
        evaluation = evaluator.evaluate(
            question=request.message,
            sql_query=str(result.get("sql") or ""),
            execution_payload={
                "sql_execution_success": bool(result.get("success", True)),
                "repair_attempts": result.get("repair_attempts", 0),
            },
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
        )
        result["quality_score"] = evaluation.quality_score
        result["confidence_score"] = evaluation.confidence_score
    except Exception:
        pass

    return ChatResponse(**result)


@router.get("/history")
async def get_history(session_id: str = "default_session"):
    """Get conversation history turns for a given session ID."""
    memory = memory_manager.get_memory(session_id)
    turns = []
    for turn in reversed(memory.turns):
        turns.append({
            "question": turn.question,
            "sql": turn.sql,
            "result_summary": turn.result_summary,
            "intent": turn.intent,
            "timestamp": turn.timestamp,
        })
    return {"session_id": session_id, "turns": turns}


@router.delete("/history")
async def clear_history(session_id: str):
    """Clear conversation history for a given session ID."""
    memory_manager.clear_memory(session_id)
    return {"status": "cleared"}

