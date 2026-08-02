from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.sql_renderer.models import SQLDocument
from app.sql_renderer.service import SQLRenderingService

router = APIRouter(prefix="/sql", tags=["sql_renderer"])

class RenderSQLRequest(BaseModel):
    query_id: str

@router.post("/render", response_model=SQLDocument)
@inject
def render_sql(
    request: RenderSQLRequest,
    sql_service: SQLRenderingService = Depends(Provide[Container.sql_rendering_service])
):
    try:
        return sql_service.render(request.query_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/{query_id}", response_model=SQLDocument)
@inject
def get_sql_document(
    query_id: str,
    sql_service: SQLRenderingService = Depends(Provide[Container.sql_rendering_service])
):
    doc = sql_service.get_document(query_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SQL Document not found")
    return doc
