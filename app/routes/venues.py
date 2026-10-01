from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import public_cache
from app.db.dependencies import get_session
from app.db.models import District, VenueType
from app.schemas.venue_import import SLUG_PATTERN
from app.schemas.venues import HallDocument, VenueDetail, VenuePage
from app.services import venues as service

router = APIRouter(prefix="/venues", tags=["Venues"], dependencies=[Depends(public_cache)])

Session = Annotated[AsyncSession, Depends(get_session)]
VenueSlug = Annotated[str, Path(pattern=SLUG_PATTERN, max_length=150)]
HallSlug = Annotated[str, Path(pattern=SLUG_PATTERN, max_length=80)]
NameSearch = Annotated[str | None, Query(min_length=2, max_length=100, description="Name contains")]


@router.get(
    "",
    summary="List venues",
    description="Published venues, sorted by name. Search by name and filter by city, "
    "district or venue type.",
)
async def list_venues(
    session: Session,
    q: NameSearch = None,
    city: Annotated[str | None, Query(pattern=SLUG_PATTERN, description="City slug")] = None,
    district: District | None = None,
    venue_type: Annotated[VenueType | None, Query(alias="type")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VenuePage:
    filters = service.VenueFilters(q=q, city=city, district=district, venue_type=venue_type)
    return await service.list_venues(session, filters, limit=limit, offset=offset)


@router.get("/{venue_slug}", summary="Venue details with its halls")
async def get_venue(session: Session, venue_slug: VenueSlug) -> VenueDetail:
    return await service.get_venue(session, venue_slug)


@router.get(
    "/{venue_slug}/halls/{hall_slug}",
    summary="Hall technical document",
    description="All technical fields of the hall, a short factual note per field "
    "(field_notes) and items particular to this hall (extras).",
)
async def get_hall(session: Session, venue_slug: VenueSlug, hall_slug: HallSlug) -> HallDocument:
    return await service.get_hall(session, venue_slug, hall_slug)
