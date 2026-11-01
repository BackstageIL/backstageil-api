from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import public_cache
from app.db.dependencies import get_session
from app.schemas.site import SiteSnapshot
from app.services.pictures import get_pictures_base_url
from app.services.recommendations import israel_today
from app.services.site_snapshot import site_snapshot

router = APIRouter(prefix="/site", tags=["Site"], dependencies=[Depends(public_cache)])


@router.get(
    "/snapshot",
    summary="All published data in one response",
    description="What the website build reads: every venue with its halls, pictures and "
    "recommendations, in the same shapes as the per-item endpoints.",
)
async def get_site_snapshot(
    session: Annotated[AsyncSession, Depends(get_session)],
    base_url: Annotated[str | None, Depends(get_pictures_base_url)],
    today: Annotated[date, Depends(israel_today)],
) -> SiteSnapshot:
    return await site_snapshot(session, base_url=base_url, today=today)
