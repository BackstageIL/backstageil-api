"""Read queries for the public API. Only published venues and halls are ever returned."""

from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import HallNotFoundError, VenueNotFoundError
from app.db.models import City, District, Hall, Venue, VenueType
from app.schemas.venues import (
    CityRef,
    CityWithCount,
    HallDocument,
    HallSummary,
    VenueDetail,
    VenuePage,
    VenueRef,
    VenueSummary,
)


@dataclass(frozen=True)
class VenueFilters:
    q: str | None = None
    city: str | None = None
    district: District | None = None
    venue_type: VenueType | None = None


def _published_hall_count() -> Select[tuple[int]]:
    return select(func.count(Hall.id)).where(Hall.venue_id == Venue.id, Hall.is_published)


def _filtered_venues(filters: VenueFilters) -> Select[tuple[Venue, City]]:
    query = select(Venue, City).join(City, City.id == Venue.city_id).where(Venue.is_published)
    if filters.q:
        query = query.where(Venue.name.ilike(f"%{filters.q}%"))
    if filters.city:
        query = query.where(City.slug == filters.city)
    if filters.district:
        query = query.where(City.district == filters.district)
    if filters.venue_type:
        query = query.where(Venue.venue_type == filters.venue_type)
    return query


async def list_venues(
    session: AsyncSession, filters: VenueFilters, *, limit: int, offset: int
) -> VenuePage:
    base = _filtered_venues(filters)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))

    hall_count = _published_hall_count().scalar_subquery()
    rows = await session.execute(
        base.add_columns(hall_count).order_by(Venue.name, Venue.id).limit(limit).offset(offset)
    )
    items = [
        VenueSummary(
            slug=venue.slug,
            name=venue.name,
            venue_type=venue.venue_type,
            street_address=venue.street_address,
            city=CityRef.model_validate(city),
            hall_count=count,
        )
        for venue, city, count in rows
    ]
    return VenuePage(items=items, total=total or 0, limit=limit, offset=offset)


async def get_venue(session: AsyncSession, venue_slug: str) -> VenueDetail:
    row = (
        await session.execute(
            select(Venue, City)
            .join(City, City.id == Venue.city_id)
            .where(Venue.slug == venue_slug, Venue.is_published)
        )
    ).one_or_none()
    if row is None:
        raise VenueNotFoundError(venue_slug)
    venue, city = row

    halls = await session.scalars(
        select(Hall).where(Hall.venue_id == venue.id, Hall.is_published).order_by(Hall.name)
    )
    return VenueDetail(
        slug=venue.slug,
        name=venue.name,
        venue_type=venue.venue_type,
        street_address=venue.street_address,
        website=venue.website,
        city=CityRef.model_validate(city),
        halls=[HallSummary.model_validate(hall) for hall in halls],
    )


async def get_hall(session: AsyncSession, venue_slug: str, hall_slug: str) -> HallDocument:
    row = (
        await session.execute(
            select(Hall, Venue, City)
            .join(Venue, Venue.id == Hall.venue_id)
            .join(City, City.id == Venue.city_id)
            .where(
                Venue.slug == venue_slug,
                Venue.is_published,
                Hall.slug == hall_slug,
                Hall.is_published,
            )
        )
    ).one_or_none()
    if row is None:
        raise HallNotFoundError(venue_slug, hall_slug)
    hall, venue, city = row

    venue_ref = VenueRef(
        slug=venue.slug,
        name=venue.name,
        street_address=venue.street_address,
        city=CityRef.model_validate(city),
    )
    technical = {name: getattr(hall, name) for name in HallDocument.model_fields if name != "venue"}
    return HallDocument.model_validate(technical | {"venue": venue_ref})


async def list_cities_with_venues(session: AsyncSession) -> list[CityWithCount]:
    rows = await session.execute(
        select(City, func.count(Venue.id))
        .join(Venue, Venue.city_id == City.id)
        .where(Venue.is_published)
        .group_by(City.id)
        .order_by(City.name_en)
    )
    return [
        CityWithCount(
            slug=city.slug, name_en=city.name_en, district=city.district, venue_count=count
        )
        for city, count in rows
    ]
