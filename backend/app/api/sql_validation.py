from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.sql_validation.models import ValidationResult
from app.sql_validation.service import SQLValidationService

router = APIRouter(prefix="/sql_validation", tags=["sql_validation"])

class ValidateSQLRequest(BaseModel):
    query_id: str
    policy: str = "ANALYST"

@router.post("/validate", response_model=ValidationResult)
@inject
def validate_sql(
    request: ValidateSQLRequest,
    validation_service: SQLValidationService = Depends(Provide[Container.sql_validation_service])
):
    try:
        return validation_service.validate_query(request.query_id, request.policy)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
