from fastapi import APIRouter, Depends, HTTPException, status
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.context_builder.models import StructuredContext, ContextBuildRequest
from app.context_builder.service import ContextBuilderService

router = APIRouter(prefix="/context", tags=["context_builder"])

@router.post("/build", response_model=StructuredContext)
@inject
def build_context(
    request: ContextBuildRequest,
    context_service: ContextBuilderService = Depends(Provide[Container.context_builder_service])
):
    try:
        return context_service.build_context(request)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/{context_id}", response_model=StructuredContext)
@inject
def get_context(
    context_id: str,
    context_service: ContextBuilderService = Depends(Provide[Container.context_builder_service])
):
    try:
        return context_service.get_context(context_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
