from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import public_cache
from app.db.dependencies import get_session
from app.schemas.venues import CityWithCount
from app.services import venues as service

router = APIRouter(prefix="/cities", tags=["Cities"], dependencies=[Depends(public_cache)])


@router.get(
    "",
    summary="Cities with venues",
    description="Only cities that have published venues, with how many (for filters).",
)
async def list_cities(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[CityWithCount]:
    return await service.list_cities_with_venues(session)
