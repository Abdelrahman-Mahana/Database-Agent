import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.core.config.settings import get_settings
from app.api.endpoints import router as api_router
from app.core.telemetry.logging import setup_logging
from app.core.middleware.logging import LoggingMiddleware
from app.core.exceptions.handlers import setup_exception_handlers
from app.utils.cache import clear_all_caches
from app.services.jobs.durable_queue import get_durable_job_queue
from app.agent.llm.model import run_openrouter_pricing_refresh
from app.services.database.db import reset_database_layer, current_session_id

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Manage the startup and shutdown lifecycle of the FastAPI application.

    This context manager handles the initialization of core services (logging,
    cache clearing, background jobs) upon startup, and ensures graceful 
    teardown of connections (database, background tasks) upon shutdown.

    Args:
        app (FastAPI): The running FastAPI application instance.

    Yields:
        None: Yields control back to the application while it runs.
    """
    # ---------------- Startup Sequence ----------------
    setup_logging()
    logger.info("Starting up AI Database Analyst Agent (Reloaded)...")
    
    clear_all_caches()
    
    # Recover stalled durable jobs (e.g., interrupted profiling)
    try:
        recovered_jobs = get_durable_job_queue().recover_stalled_jobs()
        if recovered_jobs:
            logger.info("Queued stalled onboarding jobs for recovery", count=len(recovered_jobs))
    except Exception as exc:
        logger.warning("Unable to recover stalled onboarding jobs", error=str(exc))
        
    pricing_refresh_task = None
    app_settings = get_settings()
    
    # Initialize background pricing refresh for OpenRouter
    if app_settings.llm_provider.lower() == "openrouter" and app_settings.openrouter_api_key:
        pricing_refresh_task = asyncio.create_task(run_openrouter_pricing_refresh())
    
    logger.info("Startup complete.")
    
    # Yield control to the application
    yield
    
    # ---------------- Shutdown Sequence ----------------
    if pricing_refresh_task is not None:
        pricing_refresh_task.cancel()
        try:
            await pricing_refresh_task
        except asyncio.CancelledError:
            pass
            
    try:
        reset_database_layer()
        clear_all_caches()
    except Exception as cleanup_err:
        logger.debug("Error during shutdown cleanup: %s", cleanup_err)
        
    logger.info("Shutting down AI Database Analyst Agent...")


def create_app() -> FastAPI:
    """
    Factory function to initialize and configure the FastAPI application.

    Registers middlewares, exception handlers, and API routers. It also sets up
    session management for the multi-turn conversational AI context.

    Returns:
        FastAPI: The fully configured FastAPI application instance.
    """
    settings = get_settings()
    
    app = FastAPI(
        title=settings.project_name,
        version=settings.version,
        lifespan=lifespan
    )
    
    # 1. Mount Middlewares
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(LoggingMiddleware)
    
    # 2. Session Context Middleware
    @app.middleware("http")
    async def session_middleware(request: Request, call_next):
        """
        Extract the session ID from the request headers and set it in the
        ContextVar for global access within the current execution scope.
        """
        session_id = request.headers.get("x-session-id", "default_session")
        token = current_session_id.set(session_id)
        try:
            response = await call_next(request)
            return response
        finally:
            current_session_id.reset(token)
            
    # 3. Mount Handlers & Routers
    setup_exception_handlers(app)
    app.include_router(api_router)
    
    return app


app = create_app()
