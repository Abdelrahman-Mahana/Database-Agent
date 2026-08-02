from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.dialect.models import DialectQuery
from app.dialect.service import DialectTranslationService

router = APIRouter(prefix="/dialect", tags=["dialect"])

class TranslateQueryRequest(BaseModel):
    logical_query_id: str
    dialect_name: str

@router.post("/translate", response_model=DialectQuery)
@inject
def translate_query(
    request: TranslateQueryRequest,
    dialect_service: DialectTranslationService = Depends(Provide[Container.dialect_service])
):
    try:
        return dialect_service.translate(request.logical_query_id, request.dialect_name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/{query_id}", response_model=DialectQuery)
@inject
def get_dialect_query(
    query_id: str,
    dialect_service: DialectTranslationService = Depends(Provide[Container.dialect_service])
):
    dq = dialect_service.get_query(query_id)
    if not dq:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dialect Query AST not found")
    return dq
