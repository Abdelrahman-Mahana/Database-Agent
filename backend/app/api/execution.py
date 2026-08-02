from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.execution.models import ExecutionResult, ConnectionConfig
from app.execution.service import ExecutionService

router = APIRouter(prefix="/execution", tags=["execution"])

class RunQueryRequest(BaseModel):
    query_id: str
    config: ConnectionConfig

class CancelExecutionRequest(BaseModel):
    execution_id: str

@router.post("/run", response_model=ExecutionResult)
@inject
def run_execution(
    request: RunQueryRequest,
    execution_service: ExecutionService = Depends(Provide[Container.execution_service])
):
    try:
        return execution_service.run_query(request.query_id, request.config)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.post("/cancel")
@inject
def cancel_execution(
    request: CancelExecutionRequest,
    execution_service: ExecutionService = Depends(Provide[Container.execution_service])
):
    success = execution_service.cancel_execution(request.execution_id)
    if not success:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found or already completed/cancelled")
    return {"message": "Cancellation requested successfully", "execution_id": request.execution_id}

@router.get("/{execution_id}", response_model=ExecutionResult)
@inject
def get_execution(
    execution_id: str,
    execution_service: ExecutionService = Depends(Provide[Container.execution_service])
):
    try:
        return execution_service.get_execution_status(execution_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
