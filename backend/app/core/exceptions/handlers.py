from fastapi import Request, FastAPI
from fastapi.responses import JSONResponse
import structlog

logger = structlog.get_logger(__name__)

async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

def setup_exception_handlers(app: FastAPI):
    app.add_exception_handler(Exception, global_exception_handler)
