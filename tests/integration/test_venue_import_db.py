from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnknownCityError
from app.db.models import City, District, Hall, LocalityType, Venue
from app.schemas.venue_import import VenueImportItem
from app.services.venue_import import import_venue

pytestmark = pytest.mark.anyio

CITY_CODE = 990_301  # far outside the real CBS range


def make_item(**hall: Any) -> VenueImportItem:
    return VenueImportItem.model_validate(
        {
            "venue": {
                "slug": "test-import-venue",
                "name": "Test Import Venue",
                "city_code": CITY_CODE,
                "street_address": "1 Test St",
                "venue_type": "culture_hall",
            },
            "hall": {"slug": "main", "name": "Main hall", "capacity_seated": 500} | hall,
        }
    )


@pytest.fixture
async def city(session: AsyncSession) -> City:
    city = City(
        official_code=CITY_CODE,
        name_en="Test Import City",
        name_he="עיר",
        slug="test-import-city",
        district=District.CENTER,
        locality_type=LocalityType.CITY,
    )
    session.add(city)
    await session.flush()
    return city


async def test_import_creates_then_updates_without_duplicates(
    session: AsyncSession, city: City
) -> None:
    first = await import_venue(session, make_item())
    assert (first.venue_created, first.hall_created) == (True, True)

    second = await import_venue(
        session,
        make_item(capacity_seated=650, extras={"green_room": {"value": True}}),
        publish=True,
    )
    assert (second.venue_created, second.hall_created) == (False, False)

    venue = await session.scalar(select(Venue).where(Venue.slug == "test-import-venue"))
    assert venue is not None
    assert venue.city_id == city.id
    halls = (await session.scalars(select(Hall).where(Hall.venue_id == venue.id))).all()
    assert len(halls) == 1
    await session.refresh(halls[0])
    await session.refresh(venue)
    assert halls[0].capacity_seated == 650
    assert halls[0].extras == {"green_room": {"value": True}}
    assert venue.is_published and halls[0].is_published


async def test_second_hall_in_the_same_venue(session: AsyncSession, city: City) -> None:
    await import_venue(session, make_item())
    result = await import_venue(session, make_item(slug="small", name="Small hall"))

    assert (result.venue_created, result.hall_created) == (False, True)
    count = await session.scalar(
        select(func.count()).select_from(Hall).join(Venue).where(Venue.slug == "test-import-venue")
    )
    assert count == 2


async def test_decimals_are_stored_exactly(session: AsyncSession, city: City) -> None:
    await import_venue(session, make_item(grid_height_m=7.5))

    height = await session.scalar(
        select(Hall.grid_height_m).join(Venue).where(Venue.slug == "test-import-venue")
    )
    assert height == Decimal("7.50")


async def test_unknown_city_is_rejected(session: AsyncSession) -> None:
    with pytest.raises(UnknownCityError) as error:
        await import_venue(session, make_item())

    assert error.value.details == {"city_code": CITY_CODE}
