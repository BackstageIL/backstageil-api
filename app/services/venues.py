"""
Read queries for venues, halls and cities.

The public API always uses published_only=True; the admin API passes published_only=False and
admin models (which add `is_published`). The same queries serve both.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

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
    VenueRef,
    VenueSummary,
)


@dataclass(frozen=True)
class VenueFilters:
    q: str | None = None
    city: str | None = None
    district: District | None = None
    venue_type: VenueType | None = None
    published: bool | None = None  # admin only: filter on visibility


def _hall_count(published_only: bool) -> Select[tuple[int]]:
    query = select(func.count(Hall.id)).where(Hall.venue_id == Venue.id)
    return query.where(Hall.is_published) if published_only else query


def _filtered_venues(filters: VenueFilters, published_only: bool) -> Select[tuple[Venue, City]]:
    query = select(Venue, City).join(City, City.id == Venue.city_id)
    if published_only:
        query = query.where(Venue.is_published)
    if filters.published is not None:
        query = query.where(Venue.is_published.is_(filters.published))
    if filters.q:
        # autoescape: % and _ in the search text are plain characters, not wildcards
        query = query.where(Venue.name.icontains(filters.q, autoescape=True))
    if filters.city:
        query = query.where(City.slug == filters.city)
    if filters.district:
        query = query.where(City.district == filters.district)
    if filters.venue_type:
        query = query.where(Venue.venue_type == filters.venue_type)
    return query


def _sorted_with_hall_count(
    base: Select[tuple[Venue, City]], published_only: bool
) -> Select[tuple[Venue, City, int]]:
    hall_count = _hall_count(published_only).scalar_subquery()
    return base.add_columns(hall_count).order_by(Venue.name, Venue.id)


def venue_summary[S: VenueSummary](venue: Venue, city: City, count: int, *, model: type[S]) -> S:
    return model(
        slug=venue.slug,
        name=venue.name,
        name_he=venue.name_he,
        venue_type=venue.venue_type,
        street_address=venue.street_address,
        street_address_he=venue.street_address_he,
        city=CityRef.model_validate(city),
        hall_count=count,
        is_published=venue.is_published,  # ignored by the public model
    )


async def list_venues[S: VenueSummary](
    session: AsyncSession,
    filters: VenueFilters,
    *,
    limit: int,
    offset: int,
    published_only: bool = True,
    model: type[S] = VenueSummary,  # type: ignore[assignment]
) -> tuple[list[S], int]:
    base = _filtered_venues(filters, published_only)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.execute(
        _sorted_with_hall_count(base, published_only).limit(limit).offset(offset)
    )
    items = [venue_summary(venue, city, count, model=model) for venue, city, count in rows]
    return items, total or 0


async def published_venues(session: AsyncSession) -> list[tuple[Venue, City, int]]:
    """Every published venue with its city and hall count, in the order of the public list."""
    base = _filtered_venues(VenueFilters(), published_only=True)
    rows = await session.execute(_sorted_with_hall_count(base, published_only=True))
    return [(venue, city, count) for venue, city, count in rows]


async def find_venue(session: AsyncSession, venue_slug: str, *, published_only: bool) -> Venue:
    query = select(Venue).where(Venue.slug == venue_slug)
    if published_only:
        query = query.where(Venue.is_published)
    venue = await session.scalar(query)
    if venue is None:
        raise VenueNotFoundError(venue_slug)
    return venue


async def find_hall(
    session: AsyncSession, venue_slug: str, hall_slug: str, *, published_only: bool
) -> Hall:
    query = (
        select(Hall)
        .join(Venue, Venue.id == Hall.venue_id)
        .where(Venue.slug == venue_slug, Hall.slug == hall_slug)
    )
    if published_only:
        query = query.where(Venue.is_published, Hall.is_published)
    hall = await session.scalar(query)
    if hall is None:
        raise HallNotFoundError(venue_slug, hall_slug)
    return hall


async def _city_ref(session: AsyncSession, city_id: int) -> CityRef:
    city = await session.get_one(City, city_id)
    return CityRef.model_validate(city)


def venue_detail[D: VenueDetail](
    venue: Venue,
    city: CityRef,
    halls: Iterable[Hall],
    *,
    model: type[D],
    hall_model: type[HallSummary] = HallSummary,
) -> D:
    return model(
        slug=venue.slug,
        name=venue.name,
        name_he=venue.name_he,
        venue_type=venue.venue_type,
        street_address=venue.street_address,
        street_address_he=venue.street_address_he,
        website=venue.website,
        city=city,
        halls=[hall_model.model_validate(hall) for hall in halls],
        is_published=venue.is_published,  # ignored by the public model
    )


async def get_venue[D: VenueDetail](
    session: AsyncSession,
    venue_slug: str,
    *,
    published_only: bool = True,
    model: type[D] = VenueDetail,  # type: ignore[assignment]
    hall_model: type[HallSummary] = HallSummary,
) -> D:
    venue = await find_venue(session, venue_slug, published_only=published_only)
    halls_query = select(Hall).where(Hall.venue_id == venue.id).order_by(Hall.name)
    if published_only:
        halls_query = halls_query.where(Hall.is_published)
    halls = await session.scalars(halls_query)
    city = await _city_ref(session, venue.city_id)
    return venue_detail(venue, city, halls, model=model, hall_model=hall_model)


async def get_hall[H: HallDocument](
    session: AsyncSession,
    venue_slug: str,
    hall_slug: str,
    *,
    published_only: bool = True,
    model: type[H] = HallDocument,  # type: ignore[assignment]
) -> H:
    hall = await find_hall(session, venue_slug, hall_slug, published_only=published_only)
    return await hall_document(session, hall, model=model)


def venue_ref(venue: Venue, city: CityRef) -> VenueRef:
    return VenueRef(
        slug=venue.slug,
        name=venue.name,
        name_he=venue.name_he,
        street_address=venue.street_address,
        street_address_he=venue.street_address_he,
        city=city,
    )


def build_hall_document[H: HallDocument](hall: Hall, venue: VenueRef, *, model: type[H]) -> H:
    values: dict[str, Any] = {
        name: getattr(hall, name) for name in model.model_fields if name != "venue"
    }
    return model.model_validate(values | {"venue": venue})


async def hall_document[H: HallDocument](session: AsyncSession, hall: Hall, *, model: type[H]) -> H:
    venue = await session.get_one(Venue, hall.venue_id)
    ref = venue_ref(venue, await _city_ref(session, venue.city_id))
    return build_hall_document(hall, ref, model=model)


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
            slug=city.slug,
            name_en=city.name_en,
            name_he=city.name_he,
            district=city.district,
            venue_count=count,
        )
        for city, count in rows
    ]
