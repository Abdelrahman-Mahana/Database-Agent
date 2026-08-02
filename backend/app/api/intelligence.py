from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.database.intelligence.models import SchemaIntelligence
from app.database.intelligence.service import SchemaIntelligenceService

router = APIRouter(prefix="/database/intelligence", tags=["intelligence"])

class BuildRequest(BaseModel):
    plugin_name: str

@router.post("/build", response_model=SchemaIntelligence)
@inject
async def build_intelligence(
    request: BuildRequest,
    intelligence_service: SchemaIntelligenceService = Depends(Provide[Container.intelligence_service])
):
    try:
        return await intelligence_service.build_intelligence(request.plugin_name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/{plugin_name}", response_model=SchemaIntelligence)
@inject
async def get_intelligence(
    plugin_name: str,
    intelligence_service: SchemaIntelligenceService = Depends(Provide[Container.intelligence_service])
):
    intel = intelligence_service.get_intelligence(plugin_name)
    if not intel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No intelligence built yet.")
    return intel

@router.post("/refresh", response_model=SchemaIntelligence)
@inject
async def refresh_intelligence(
    request: BuildRequest,
    intelligence_service: SchemaIntelligenceService = Depends(Provide[Container.intelligence_service])
):
    try:
        intelligence_service.clear(request.plugin_name)
        return await intelligence_service.build_intelligence(request.plugin_name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
