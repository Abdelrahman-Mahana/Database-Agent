from fastapi import APIRouter, Depends, HTTPException, status
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.ai_reasoning.models import AIResponse, AIReasoningRequest
from app.ai_reasoning.service import AIReasoningService

router = APIRouter(prefix="/ai", tags=["ai_reasoning"])

@router.post("/answer", response_model=AIResponse)
@inject
def get_answer(
    request: AIReasoningRequest,
    ai_service: AIReasoningService = Depends(Provide[Container.ai_reasoning_service])
):
    try:
        return ai_service.process_reasoning(request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
