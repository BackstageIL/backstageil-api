from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.exceptions import DatabaseUnavailableError
from app.core.logger import get_logger
from app.db.dependencies import get_database
from app.db.session import Database
from app.schemas.health import HealthResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", summary="Liveness check")
# HEAD too (hidden from the docs): uptime monitors often probe with HEAD and read 405 as "down"
@router.head("", include_in_schema=False)
async def liveness() -> HealthResponse:
    """The process is up. No dependencies are checked (used by the platform to restart the app)."""
    return HealthResponse()


@router.get("/ready", summary="Readiness check")
@router.head("/ready", include_in_schema=False)
async def readiness(database: Annotated[Database, Depends(get_database)]) -> HealthResponse:
    """The app can serve traffic: the database is configured and reachable (used before a
    blue-green switch)."""
    try:
        await database.ping()
    except Exception as exc:
        logger.warning("Readiness check failed: %s", exc)
        raise DatabaseUnavailableError() from exc
    return HealthResponse()
