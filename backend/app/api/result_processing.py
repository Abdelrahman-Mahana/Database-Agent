from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.result_processing.models import ProcessedResult, ResultProcessingConfig
from app.result_processing.service import ResultProcessingService

router = APIRouter(prefix="/results", tags=["result_processing"])

class ProcessResultRequest(BaseModel):
    execution_id: str
    config: ResultProcessingConfig

@router.post("/process", response_model=ProcessedResult)
@inject
def process_result(
    request: ProcessResultRequest,
    processing_service: ResultProcessingService = Depends(Provide[Container.result_processing_service])
):
    try:
        if request.config.streaming:
            generator = processing_service.stream_result(request.execution_id, request.config)
            return StreamingResponse(generator, media_type="application/x-ndjson")
        else:
            return processing_service.process_result(request.execution_id, request.config)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/{result_id}", response_model=ProcessedResult)
@inject
def get_result(
    result_id: str,
    processing_service: ResultProcessingService = Depends(Provide[Container.result_processing_service])
):
    try:
        return processing_service.get_processed_result(result_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
