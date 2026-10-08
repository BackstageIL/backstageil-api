"""Create or update a venue and its hall from a validated import item (idempotent, by slug)."""

from dataclasses import dataclass

from sqlalchemy import Boolean, func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import ColumnClause

from app.core.exceptions import DuplicateSlugsError, UnknownCityError
from app.db.models import City, Hall, Venue
from app.schemas.admin import ImportReport
from app.schemas.venue_import import VenueImportItem


@dataclass(frozen=True)
class ImportResult:
    venue_slug: str
    hall_slug: str
    venue_created: bool
    hall_created: bool


# xmax = 0 on the returned row means it was inserted, not updated (PostgreSQL)
_INSERTED: ColumnClause[bool] = literal_column("xmax = 0", type_=Boolean)


async def import_venue(
    session: AsyncSession, item: VenueImportItem, *, publish: bool = False
) -> ImportResult:
    city_id = await session.scalar(
        select(City.id).where(City.official_code == item.venue.city_code)
    )
    if city_id is None:
        raise UnknownCityError(item.venue.city_code)

    # A Hebrew name left out of the item keeps the one already stored (English-only re-imports)
    keep_he = {"name_he"} if item.venue.name_he is None else set()
    venue_values = item.venue.model_dump(exclude={"city_code", "website", *keep_he})
    venue_values |= {
        "city_id": city_id,
        "website": str(item.venue.website) if item.venue.website else None,
        "is_published": publish,
    }
    venue_insert = insert(Venue).values(**venue_values)
    venue_row = (
        await session.execute(
            venue_insert.on_conflict_do_update(
                index_elements=[Venue.slug],
                set_={
                    **{k: venue_insert.excluded[k] for k in venue_values if k != "slug"},
                    "updated_at": func.now(),
                },
            ).returning(Venue.id, _INSERTED)
        )
    ).one()

    hall_values = item.hall_values() | {"venue_id": venue_row.id, "is_published": publish}
    if item.hall.name_he is None:
        del hall_values["name_he"]
    hall_insert = insert(Hall).values(**hall_values)
    hall_row = (
        await session.execute(
            hall_insert.on_conflict_do_update(
                constraint="uq_halls_venue_id_slug",
                set_={
                    **{
                        k: hall_insert.excluded[k]
                        for k in hall_values
                        if k not in ("venue_id", "slug")
                    },
                    "updated_at": func.now(),
                },
            ).returning(Hall.id, _INSERTED)
        )
    ).one()

    return ImportResult(
        venue_slug=item.venue.slug,
        hall_slug=item.hall.slug,
        venue_created=bool(venue_row[1]),
        hall_created=bool(hall_row[1]),
    )


def duplicate_slugs(items: list[VenueImportItem]) -> list[str]:
    slugs = [item.venue.slug for item in items]
    return sorted({slug for slug in slugs if slugs.count(slug) > 1})


async def import_items(
    session: AsyncSession, items: list[VenueImportItem], *, publish: bool, dry_run: bool = False
) -> ImportReport:
    """Import every item (all-or-nothing within the caller's transaction).

    The upload decides visibility: every venue and hall gets is_published=publish.
    """
    duplicates = duplicate_slugs(items)
    if duplicates:
        raise DuplicateSlugsError(duplicates)
    results = [await import_venue(session, item, publish=publish) for item in items]
    venues_created = sum(r.venue_created for r in results)
    halls_created = sum(r.hall_created for r in results)
    return ImportReport(
        items=len(results),
        venues_created=venues_created,
        venues_updated=len(results) - venues_created,
        halls_created=halls_created,
        halls_updated=len(results) - halls_created,
        dry_run=dry_run,
    )
