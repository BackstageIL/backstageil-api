"""Admin-only routes. Every route here requires the admin API key (X-API-Key)."""

from fastapi import APIRouter, Depends, Response

from app.core.security import require_admin
from app.schemas.health import HealthResponse

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


@router.get(
    "/ping",
    summary="Check the admin key",
    description="Returns ok when X-API-Key is valid. Useful after setting or rotating the key.",
)
async def ping(response: Response) -> HealthResponse:
    response.headers["Cache-Control"] = "no-store"
    return HealthResponse()
