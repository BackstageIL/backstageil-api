"""Admin write operations on single venues and halls (edits, visibility, deletion)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConfirmationMismatchError, UnknownCityError
from app.db.models import City, Hall, Venue
from app.schemas.admin import HallPatch, PublishState, VenuePatch
from app.services.venues import find_hall, find_venue


async def patch_venue(session: AsyncSession, venue_slug: str, patch: VenuePatch) -> Venue:
    venue = await find_venue(session, venue_slug, published_only=False)
    changes = patch.model_dump(exclude_unset=True)
    if "city_code" in changes:
        code = changes.pop("city_code")
        city_id = await session.scalar(select(City.id).where(City.official_code == code))
        if city_id is None:
            raise UnknownCityError(code)
        venue.city_id = city_id
    if "website" in changes:
        changes["website"] = str(patch.website) if patch.website else None
    for field, value in changes.items():
        setattr(venue, field, value)
    await session.flush()
    return venue


async def patch_hall(
    session: AsyncSession, venue_slug: str, hall_slug: str, patch: HallPatch
) -> Hall:
    hall = await find_hall(session, venue_slug, hall_slug, published_only=False)
    changes = patch.model_dump(exclude_unset=True, exclude={"field_notes", "extras"})
    if "field_notes" in patch.model_fields_set:
        notes = patch.field_notes
        changes["field_notes"] = notes.model_dump(mode="json") if notes else {}
    if "extras" in patch.model_fields_set:
        extras = patch.extras
        changes["extras"] = extras.model_dump(mode="json", exclude_none=True) if extras else {}
    for field, value in changes.items():
        setattr(hall, field, value)
    await session.flush()
    await session.refresh(hall)  # server-side updated_at
    return hall


async def set_venue_published(
    session: AsyncSession, venue_slug: str, published: bool
) -> PublishState:
    venue = await find_venue(session, venue_slug, published_only=False)
    venue.is_published = published
    await session.flush()
    return PublishState(slug=venue.slug, is_published=venue.is_published)


async def set_hall_published(
    session: AsyncSession, venue_slug: str, hall_slug: str, published: bool
) -> PublishState:
    hall = await find_hall(session, venue_slug, hall_slug, published_only=False)
    hall.is_published = published
    await session.flush()
    return PublishState(slug=hall.slug, is_published=hall.is_published)


async def delete_venue(session: AsyncSession, venue_slug: str, confirm: str | None) -> None:
    """Permanent: the database cascades to halls, pictures and recommendations."""
    venue = await find_venue(session, venue_slug, published_only=False)
    if confirm != venue_slug:
        raise ConfirmationMismatchError(venue_slug)
    await session.delete(venue)
    await session.flush()


async def delete_hall(
    session: AsyncSession, venue_slug: str, hall_slug: str, confirm: str | None
) -> None:
    hall = await find_hall(session, venue_slug, hall_slug, published_only=False)
    if confirm != hall_slug:
        raise ConfirmationMismatchError(hall_slug)
    await session.delete(hall)
    await session.flush()
