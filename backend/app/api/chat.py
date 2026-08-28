"""Chat API routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.services.database.db import get_db
from app.agent.orchestration.analyst_agent import AnalystAgent
from app.models.schemas.chat import ChatRequest, ChatResponse, apply_chat_statuses
from app.services.memory import memory_manager
from app.utils.token_tracker import reset_token_usage, get_current_token_usage
from app.utils.cost_dashboard import cost_dashboard
from app.core.config.settings import settings
from app.agent.llm.model import get_llm_client
from app.services.evaluation import AgentEvaluator
from app.services.evaluation.models import StageLatency

router = APIRouter(prefix="/chat", tags=["chat"])
agent = AnalystAgent()
evaluator = AgentEvaluator()


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    """
    Process a natural language question and return an analytical report.

    This endpoint acts as the primary entry point for user queries. It routes the 
    question to the LangGraph AnalystAgent, records token usage, evaluates the 
    quality of the execution, and returns a comprehensive report.

    Args:
        request (ChatRequest): The incoming request payload containing the user's message.
        db (Session): The active SQLAlchemy database session dependency.

    Returns:
        ChatResponse: A structured response containing the analytical report, generated SQL,
            chart suggestions, and execution metadata (tokens, latency, quality scores).

    Raises:
        HTTPException: If the provided message is empty or exclusively whitespace.
    """
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    reset_token_usage()
    
    # Execute the primary agent pipeline
    result = await agent.ask(request.message, db, session_id=request.session_id)
    
    # ---------------- Token Calculation ----------------
    usage = get_current_token_usage()
    if usage["prompt_tokens"] == 0 and usage["completion_tokens"] == 0:
        # Fallback estimation if token tracking was disabled or unavailable
        usage["prompt_tokens"] = max(10, len(request.message) // 4)
        resp_text = str(result.get("report") or result.get("answer") or result.get("sql") or "")
        usage["completion_tokens"] = max(15, len(resp_text) // 4)
        
    result["prompt_tokens"] = usage["prompt_tokens"]
    result["completion_tokens"] = usage["completion_tokens"]
    result["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    
    apply_chat_statuses(result)

    # ---------------- Cost Dashboard Logging ----------------
    # Best-effort logging: Never let tracking failures affect the actual response.
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

    # ---------------- AI Evaluation Framework ----------------
    # Score this request (queryable via GET /evaluation/history and /evaluation/stats).
    try:
        timings = result.get("timings_ms", {})
        has_sql = bool(result.get("sql"))
        has_error = bool(result.get("error")) or result.get("error_type") in (
            "execution_error", "sql_error", "orchestrator_failure", "safety", 
            "identifier_grounding", "join_validation", "syntax_error"
        )
        has_results = result.get("results") is not None and len(result.get("results", [])) > 0
        
        repair_cnt = int(
            result.get("sql_repair_attempts", 0)
            or result.get("repair_attempts", 0)
            or timings.get("sql_repair_attempts", 0)
            or 0
        )

        sql_gen_ok = has_sql and result.get("error_type") not in ("syntax_error", "unanswerable", "safety")
        sql_exec_ok = has_sql and not has_error and result.get("results") is not None and result.get("error") is None
        grounding_ok = (
            result.get("sql_validation", {}).get("identifiers_valid", True)
            and result.get("sql_validation", {}).get("joins_valid", True)
            and result.get("error_type") not in ("identifier_grounding", "join_validation")
        )
        analytics_ok = bool(result.get("analysis_result") or result.get("analytics_result") or (has_results and not has_error))
        insight_ok = bool(result.get("insight_result") or (has_results and not has_error))
        report_ok = bool(result.get("report") and not has_error)
        chart_ok = bool(result.get("chart_suggestion"))

        stage_latency = StageLatency(
            intent_classification_ms=float(timings.get("query_understanding_ms", 0.0)),
            schema_grounding_ms=float(timings.get("schema_grounding_ms", 0.0)),
            sql_generation_ms=float(timings.get("sql_generation_ms", 0.0)),
            sql_execution_ms=float(timings.get("sql_execution_ms", 0.0)),
            analytics_ms=float(timings.get("analytics_ms", 0.0)),
            insight_ms=float(timings.get("insight_ms", 0.0)),
            report_generation_ms=float(timings.get("report_generation_ms", 0.0)),
            chart_suggestion_ms=float(timings.get("chart_suggestion_ms", 0.0)),
            total_ms=float(timings.get("total_request_time_ms", 0.0)),
        )

        evaluation = evaluator.evaluate(
            question=request.message,
            sql_query=str(result.get("sql") or ""),
            execution_payload={
                "sql_generation_success": sql_gen_ok,
                "sql_execution_success": sql_exec_ok,
                "repair_attempts": repair_cnt,
                "grounding_validation_success": grounding_ok,
                "analytics_success": analytics_ok,
                "insight_success": insight_ok,
                "report_success": report_ok,
                "chart_success": chart_ok,
            },
            stage_latency=stage_latency,
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
        )
        
        result["quality_score"] = evaluation.quality_score
        result["confidence_score"] = evaluation.confidence_score
        
    except Exception:
        pass

    return ChatResponse(**result)


@router.get("/history")
async def get_history(session_id: str = "default_session") -> dict:
    """
    Retrieve the conversational history for a given session.

    Iterates through the active memory window and returns previous turns
    to maintain context across the UI.

    Args:
        session_id (str): The unique identifier for the user session. 
            Defaults to 'default_session'.

    Returns:
        dict: A dictionary containing the `session_id` and a list of `turns`.
    """
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
async def clear_history(session_id: str) -> dict:
    """
    Clear the conversation history for a given session.

    Args:
        session_id (str): The unique identifier for the user session to clear.

    Returns:
        dict: A confirmation message indicating the status of the operation.
    """
    memory_manager.clear_memory(session_id)
    return {"status": "cleared"}
