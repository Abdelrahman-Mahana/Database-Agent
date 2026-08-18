from fastapi import APIRouter
from app.api.schema import router as schema_router
from app.api.connect import router as connect_router
from app.api.chat import router as chat_router
from app.api.memory import router as memory_router
from app.api.stats import router as stats_router
from app.api.health import router as health_router
from app.api.evaluation import router as evaluation_router

router = APIRouter()
router.include_router(schema_router)
router.include_router(connect_router)
router.include_router(chat_router)
router.include_router(memory_router)
router.include_router(stats_router)
router.include_router(health_router)
router.include_router(evaluation_router)

@router.get("/readiness", tags=["system"])
async def readiness_check():
    """Check if the application is ready to accept traffic."""
    return {
        "status": "ready"
    }

@router.get("/liveness", tags=["system"])
async def liveness_check():
    """Check if the application is alive."""
    return {"status": "alive"}
