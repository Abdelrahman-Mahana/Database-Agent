from fastapi import APIRouter, Depends
from dependency_injector.wiring import inject, Provide
from app.core.container import Container
from app.api.discovery import router as discovery_router
from app.api.intelligence import router as intelligence_router
from app.api.profiling import router as profiling_router
from app.api.query_understanding import router as query_understanding_router
from app.api.planning import router as planning_router
from app.api.logical_query import router as logical_query_router
from app.api.dialect import router as dialect_router
from app.api.sql_renderer import router as sql_renderer_router
from app.api.sql_validation import router as sql_validation_router
from app.api.execution import router as execution_router
from app.api.result_processing import router as result_processing_router
from app.api.semantic_analysis import router as semantic_analysis_router
from app.api.context_builder import router as context_builder_router
from app.api.ai_reasoning import router as ai_reasoning_router
from app.api.conversation import router as conversation_router
from app.api.orchestrator import router as orchestrator_router
from app.api.schema import router as schema_router
from app.api.connect import router as connect_router
from app.api.chat import router as chat_router
from app.api.memory import router as memory_router
from app.api.stats import router as stats_router
from app.api.health import router as health_router
from app.api.evaluation import router as evaluation_router

router = APIRouter()
router.include_router(discovery_router)
router.include_router(intelligence_router)
router.include_router(profiling_router)
router.include_router(query_understanding_router)
router.include_router(planning_router)
router.include_router(logical_query_router)
router.include_router(dialect_router)
router.include_router(sql_renderer_router)
router.include_router(sql_validation_router)
router.include_router(execution_router)
router.include_router(result_processing_router)
router.include_router(semantic_analysis_router)
router.include_router(context_builder_router)
router.include_router(ai_reasoning_router)
router.include_router(conversation_router)
router.include_router(orchestrator_router)
router.include_router(schema_router)
router.include_router(connect_router)
router.include_router(chat_router)
router.include_router(memory_router)
router.include_router(stats_router)
router.include_router(health_router)
router.include_router(evaluation_router)


@router.get("/readiness", tags=["system"])
@inject
async def readiness_check(
    # In the future, you could inject a DB ping here
    plugin_manager = Depends(Provide[Container.plugin_manager])
):
    """Check if the application is ready to accept traffic."""
    plugins_loaded = len(plugin_manager.plugins)
    return {
        "status": "ready",
        "plugins_loaded": plugins_loaded
    }

@router.get("/liveness", tags=["system"])
async def liveness_check():
    """Check if the application is alive."""
    return {"status": "alive"}
