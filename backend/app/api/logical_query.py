from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.logical_query.models import LogicalQuery
from app.logical_query.service import LogicalQueryService

router = APIRouter(prefix="/logical-query", tags=["logical_query"])

class BuildLogicalQueryRequest(BaseModel):
    plan_id: str

@router.post("/build", response_model=LogicalQuery)
@inject
def build_logical_query(
    request: BuildLogicalQueryRequest,
    lq_service: LogicalQueryService = Depends(Provide[Container.logical_query_service])
):
    try:
        return lq_service.build_query(request.plan_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/{query_id}", response_model=LogicalQuery)
@inject
def get_logical_query(
    query_id: str,
    lq_service: LogicalQueryService = Depends(Provide[Container.logical_query_service])
):
    lq = lq_service.get_query(query_id)
    if not lq:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Logical Query not found")
    return lq
