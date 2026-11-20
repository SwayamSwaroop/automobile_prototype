"""FastAPI entry point for School MenteeZ Core."""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from apps.app_logging.logging_middleware import RequestLoggingMiddleware
from apps.app_logging.logging_setup import configure_logging

from apps.settings.config import get_settings
from apps.settings.databases.postgres_db_connection import async_engine
from apps.shared.exceptions import register_exception_handlers

settings = get_settings()
logging_runtime = configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage shared resources without creating schemas or tables at startup."""
    logging_runtime.start()
    logger.info(
        "Application starting",
        extra={"event": "APPLICATION_STARTING", "category": "SYSTEM"},
    )
    try:
        logger.info(
            "Application started",
            extra={"event": "APPLICATION_STARTED", "category": "SYSTEM"},
        )
        yield
    finally:
        logger.info(
            "Application shutting down",
            extra={"event": "APPLICATION_SHUTTING_DOWN", "category": "SYSTEM"},
        )
        try:
            await async_engine.dispose()
            logger.info(
                "Database engine disposed",
                extra={"event": "DATABASE_ENGINE_DISPOSED", "category": "SYSTEM"},
            )
        except Exception:
            logger.exception(
                "Database engine failed to dispose cleanly",
                extra={"event": "DATABASE_ENGINE_DISPOSE_FAILED", "category": "SYSTEM"},
            )
        finally:
            logger.info(
                "Application shutdown complete",
                extra={"event": "APPLICATION_SHUTDOWN_COMPLETE", "category": "SYSTEM"},
            )
            # Stop logging last so resource shutdown messages can be flushed.
            logging_runtime.stop()


app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    root_path=settings.app_root_path,
    debug=settings.debug,
    lifespan=lifespan,
)
register_exception_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestLoggingMiddleware)

media_root = settings.media_root_path
media_root.mkdir(parents=True, exist_ok=True)
app.mount(
    settings.public_media_prefix,
    StaticFiles(directory=str(media_root)),
    name="media",
)


@app.get("/health", tags=["Health"], summary="Application liveness")
async def health_check() -> dict:
    """Report application liveness; this does not check PostgreSQL connectivity."""
    return {
        "message": "success",
        "data": {
            "status": "ok",
            "service": settings.app_title,
            "environment": settings.environment,
            "debug": settings.debug,
        },
        "code": "OK",
    }


# Register feature routers here as their modules are implemented.
