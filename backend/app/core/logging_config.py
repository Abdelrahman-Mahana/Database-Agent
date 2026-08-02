"""Structured logging configuration using loguru."""
import logging
import sys
from loguru import logger


def setup_logging():
    """Configure loguru for structured JSON logging and redirect standard library logs."""
    # Remove standard logging handlers
    logging.getLogger().handlers = []
    
    # Configure Loguru to serialize all logs into JSON
    logger.remove()
    logger.add(
        sys.stdout,
        serialize=True,
        level="INFO",
        backtrace=True,
        diagnose=True,
    )
    
    # Intercept standard library logs and route them to loguru
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            frame, depth = logging.currentframe(), 2
            while frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    # Force route all logs to InterceptHandler
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        logging_logger = logging.getLogger(name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False
