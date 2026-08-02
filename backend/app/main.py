from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.config.settings import get_settings
from app.core.container import Container
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
    
    # Initialize container and discover plugins
    container = app.container
    plugin_manager = container.plugin_manager()
    plugin_manager.discover_plugins()
    
    logger.info("Startup complete.")
    
    yield
    
    # Application shutdown
    logger.info("Shutting down AI Database Analyst Agent...")

def create_app() -> FastAPI:
    settings = get_settings()
    
    # Initialize DI Container
    container = Container()
    container.settings.from_pydantic(settings)
    
    app = FastAPI(
        title=settings.project_name,
        version=settings.version,
        lifespan=lifespan
    )
    
    app.container = container
    
    # Add Middlewares
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(LoggingMiddleware)
    
    # Add Exception Handlers
    setup_exception_handlers(app)
    
    # Include Routers
    app.include_router(api_router)
    
    return app

app = create_app()
