from fastapi import APIRouter, Depends, HTTPException, status
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.orchestrator.models import UserRequest, OrchestratorResponse
from app.orchestrator.service import OrchestratorService

router = APIRouter(prefix="/agent", tags=["orchestrator"])

@router.post("/query", response_model=OrchestratorResponse)
@inject
def process_query(
    request: UserRequest,
    orch_service: OrchestratorService = Depends(Provide[Container.orchestrator_service])
):
    try:
        return orch_service.process_query(request)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
