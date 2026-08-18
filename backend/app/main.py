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
    
    logger.info("Startup complete.")
    
    yield
    
    # Application shutdown
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

