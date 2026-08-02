from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.planning.models import ExecutionPlan
from app.planning.service import ExecutionPlanningService

router = APIRouter(prefix="/planning", tags=["planning"])

class CreatePlanRequest(BaseModel):
    plugin_name: str
    query: str

@router.post("/create", response_model=ExecutionPlan)
@inject
async def create_plan(
    request: CreatePlanRequest,
    planning_service: ExecutionPlanningService = Depends(Provide[Container.execution_planning_service])
):
    try:
        return await planning_service.create_plan(request.plugin_name, request.query)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/{plan_id}", response_model=ExecutionPlan)
@inject
def get_plan(
    plan_id: str,
    planning_service: ExecutionPlanningService = Depends(Provide[Container.execution_planning_service])
):
    plan = planning_service.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    return plan
