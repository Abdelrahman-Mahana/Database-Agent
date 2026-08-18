import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.config.settings import get_settings
from app.api.endpoints import router as api_router
from app.telemetry.logging import setup_logging
from app.middleware.logging import LoggingMiddleware
from app.exceptions.handlers import setup_exception_handlers

logger = structlog.get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Application startup
    setup_logging()
    logger.info("Starting up AI Database Analyst Agent...")
    # Resume profiling jobs that were interrupted by a worker restart.  The
    # queue only re-dispatches jobs after a heartbeat timeout, so this must run
    # during startup rather than waiting for another connection request.
    try:
        from app.jobs.durable_queue import get_durable_job_queue
        recovered_jobs = get_durable_job_queue().recover_stalled_jobs()
        if recovered_jobs:
            logger.info("Queued stalled onboarding jobs for recovery", count=len(recovered_jobs))
    except Exception as exc:
        logger.warning("Unable to recover stalled onboarding jobs", error=str(exc))
    pricing_refresh_task = None
    app_settings = get_settings()
    if app_settings.llm_provider.lower() == "openrouter" and app_settings.openrouter_api_key:
        from app.llm.model import run_openrouter_pricing_refresh
        # Starts with static prices available immediately; refresh happens in
        # the background and never delays startup or a user workflow.
        pricing_refresh_task = asyncio.create_task(run_openrouter_pricing_refresh())
    
    logger.info("Startup complete.")
    
    yield
    
    # Application shutdown
    if pricing_refresh_task is not None:
        pricing_refresh_task.cancel()
        try:
            await pricing_refresh_task
        except asyncio.CancelledError:
            pass
    logger.info("Shutting down AI Database Analyst Agent...")

def create_app() -> FastAPI:
    settings = get_settings()
    
    app = FastAPI(
        title=settings.project_name,
        version=settings.version,
        lifespan=lifespan
    )
    
    # Add Middlewares
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(LoggingMiddleware)
    
    from fastapi import Request
    from app.database.db import current_session_id
    
    @app.middleware("http")
    async def session_middleware(request: Request, call_next):
        # SECURITY ASSUMPTION: This application is designed as a single-user local tool.
        # The x-session-id is used purely for context separation (e.g., distinguishing between
        # browser tabs) and is not a cryptographically secure authentication token.
        # Do not deploy this as a multi-tenant service on the internet without implementing
        # proper authentication (JWT, signed cookies, etc.).
        session_id = request.headers.get("x-session-id") or "default_session"
        token = current_session_id.set(session_id)
        try:
            response = await call_next(request)
            return response
        finally:
            current_session_id.reset(token)
            
    # Add Exception Handlers
    setup_exception_handlers(app)
    
    # Include Routers
    app.include_router(api_router)
    
    return app

app = create_app()

