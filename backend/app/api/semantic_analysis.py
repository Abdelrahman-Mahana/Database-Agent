from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.semantic_analysis.models import SemanticAnalysisResult
from app.semantic_analysis.service import SemanticAnalysisService

router = APIRouter(prefix="/semantic-analysis", tags=["semantic_analysis"])

class RunAnalysisRequest(BaseModel):
    result_id: str

@router.post("/run", response_model=SemanticAnalysisResult)
@inject
def run_analysis(
    request: RunAnalysisRequest,
    analysis_service: SemanticAnalysisService = Depends(Provide[Container.semantic_analysis_service])
):
    try:
        return analysis_service.run_analysis(request.result_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/{analysis_id}", response_model=SemanticAnalysisResult)
@inject
def get_analysis(
    analysis_id: str,
    analysis_service: SemanticAnalysisService = Depends(Provide[Container.semantic_analysis_service])
):
    try:
        return analysis_service.get_analysis(analysis_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
