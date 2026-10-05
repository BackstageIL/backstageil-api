from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logger import configure_logging, get_logger
from app.core.monitoring import init_error_tracking
from app.core.security import FailedAttemptLimiter
from app.db.session import Database
from app.routes import api_router
from app.routes.health import router as health_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    if settings.database_url is None:
        logger.warning("DATABASE_URL is not set; starting without a database")
        app.state.database = None
    else:
        app.state.database = Database(
            settings.database_url.get_secret_value(),
            # serverless: each instance keeps only a tiny pool; the pooler multiplexes
            pool_size=1 if settings.db_pooled else settings.db_pool_size,
            max_overflow=2 if settings.db_pooled else settings.db_max_overflow,
            pooled=settings.db_pooled,
        )
    try:
        yield
    finally:
        if app.state.database is not None:
            await app.state.database.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    init_error_tracking(settings)

    app = FastAPI(
        title="BackstageIL API",
        description="Technical information about performance venues and halls in Israel",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = None
    app.state.picture_storage = None  # created on first use (BSIL-24)
    app.state.admin_limiter = FailedAttemptLimiter(
        settings.admin_max_failed_attempts, settings.admin_failed_window_seconds
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(api_router)
    return app


app = create_app()
