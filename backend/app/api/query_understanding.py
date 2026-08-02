from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.query_understanding.models import QueryUnderstanding
from app.query_understanding.service import QueryUnderstandingService

router = APIRouter(prefix="/query", tags=["query_understanding"])

class UnderstandRequest(BaseModel):
    plugin_name: str
    query: str

class NormalizeRequest(BaseModel):
    query: str
    
class NormalizeResponse(BaseModel):
    normalized_query: str

@router.post("/understand", response_model=QueryUnderstanding)
@inject
async def understand_query(
    request: UnderstandRequest,
    qu_service: QueryUnderstandingService = Depends(Provide[Container.query_understanding_service])
):
    try:
        return await qu_service.understand(request.plugin_name, request.query)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.post("/normalize", response_model=NormalizeResponse)
@inject
def normalize_query(
    request: NormalizeRequest,
    qu_service: QueryUnderstandingService = Depends(Provide[Container.query_understanding_service])
):
    try:
        norm = qu_service.normalize_only(request.query)
        return NormalizeResponse(normalized_query=norm)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
