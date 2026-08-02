from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.database.discovery.models import DatabaseMetadata
from app.database.discovery.service import DiscoveryService

router = APIRouter(prefix="/database", tags=["discovery"])

class DiscoverRequest(BaseModel):
    plugin_name: str

@router.post("/discover", response_model=DatabaseMetadata)
@inject
async def discover(
    request: DiscoverRequest,
    discovery_service: DiscoveryService = Depends(Provide[Container.discovery_service])
):
    try:
        return await discovery_service.discover(request.plugin_name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/metadata", response_model=DatabaseMetadata)
@inject
async def get_metadata(
    discovery_service: DiscoveryService = Depends(Provide[Container.discovery_service])
):
    metadata = discovery_service.get_metadata()
    if not metadata:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No metadata discovered yet.")
    return metadata

@router.post("/refresh", response_model=DatabaseMetadata)
@inject
async def refresh_metadata(
    request: DiscoverRequest,
    discovery_service: DiscoveryService = Depends(Provide[Container.discovery_service])
):
    try:
        return await discovery_service.refresh(request.plugin_name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
