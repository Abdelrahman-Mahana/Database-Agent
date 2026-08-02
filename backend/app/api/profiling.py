from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from dependency_injector.wiring import inject, Provide

from app.core.container import Container
from app.database.profiling.models import DatabaseProfile
from app.database.profiling.service import DataProfilingService

router = APIRouter(prefix="/database/profile", tags=["profiling"])

class ProfileRequest(BaseModel):
    plugin_name: str

@router.post("", response_model=DatabaseProfile)
@inject
async def build_profile(
    request: ProfileRequest,
    profiling_service: DataProfilingService = Depends(Provide[Container.profiling_service])
):
    try:
        return await profiling_service.build_profile(request.plugin_name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/{plugin_name}", response_model=DatabaseProfile)
@inject
async def get_profile(
    plugin_name: str,
    profiling_service: DataProfilingService = Depends(Provide[Container.profiling_service])
):
    profile = profiling_service.get_profile(plugin_name)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile built yet.")
    return profile

@router.post("/refresh", response_model=DatabaseProfile)
@inject
async def refresh_profile(
    request: ProfileRequest,
    profiling_service: DataProfilingService = Depends(Provide[Container.profiling_service])
):
    try:
        return await profiling_service.refresh_profile(request.plugin_name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
