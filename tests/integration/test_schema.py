from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    City,
    District,
    Hall,
    HallPicture,
    LocalityType,
    Recommendation,
    RecommendationCategory,
    Venue,
    VenueType,
)

pytestmark = pytest.mark.anyio

# Official codes far outside the real range, so test rows can never clash with seeded cities
_TEST_CODE = 990_000


async def _city(session: AsyncSession, code: int, name: str) -> City:
    city = City(
        official_code=_TEST_CODE + code,
        name_en=name,
        name_he=name,
        slug=f"test-{name.lower()}",
        district=District.CENTER,
        locality_type=LocalityType.CITY,
    )
    session.add(city)
    await session.flush()
    return city


async def _venue(
    session: AsyncSession, city: City, name: str, street: str | None = None, slug: str = ""
) -> Venue:
    venue = Venue(
        slug=slug or f"test-{name.lower().replace(' ', '-')}-{city.slug}-{street or 'x'}",
        name=name,
        city_id=city.id,
        street_address=street,
        venue_type=VenueType.CULTURE_HALL,
    )
    session.add(venue)
    await session.flush()
    return venue


async def _expect_integrity_error(session: AsyncSession, obj: object) -> None:
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            session.add(obj)
            await session.flush()


async def test_same_venue_name_in_two_cities_is_allowed(session: AsyncSession) -> None:
    tel_aviv = await _city(session, 1, "Testaviv")
    modiin = await _city(session, 2, "Testmodiin")

    await _venue(session, tel_aviv, "Heichal HaTarbut")
    await _venue(session, modiin, "Heichal HaTarbut")


async def test_same_name_city_and_street_is_rejected_case_insensitive(
    session: AsyncSession,
) -> None:
    city = await _city(session, 3, "Testcity")
    await _venue(session, city, "Zappa", street="Medinat Hayehudim 85", slug="test-zappa-1")

    duplicate = Venue(
        slug="test-zappa-2",
        name="ZAPPA",
        city_id=city.id,
        street_address="medinat hayehudim 85",
        venue_type=VenueType.CLUB,
    )
    await _expect_integrity_error(session, duplicate)


async def test_same_name_same_city_other_street_is_allowed(session: AsyncSession) -> None:
    city = await _city(session, 4, "Testcity")
    await _venue(session, city, "Beit HaAm", street="Main St 1", slug="test-beit-haam-1")
    await _venue(session, city, "Beit HaAm", street="Other St 9", slug="test-beit-haam-2")


async def test_duplicate_hall_slug_in_same_venue_is_rejected(session: AsyncSession) -> None:
    venue = await _venue(session, await _city(session, 5, "Testcity"), "Test Venue")
    session.add(Hall(venue_id=venue.id, slug="main", name="Main hall"))
    await session.flush()

    await _expect_integrity_error(session, Hall(venue_id=venue.id, slug="main", name="Again"))


async def test_negative_capacity_is_rejected(session: AsyncSession) -> None:
    venue = await _venue(session, await _city(session, 6, "Testcity"), "Test Venue")

    await _expect_integrity_error(
        session, Hall(venue_id=venue.id, slug="main", name="Main", capacity_seated=-1)
    )


async def test_invalid_enum_value_is_rejected_by_database(session: AsyncSession) -> None:
    city = await _city(session, 7, "Testcity")
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(
                text(
                    "INSERT INTO venues (slug, name, city_id, venue_type) "
                    "VALUES ('test-bad-type', 'Bad', :city_id, 'stadium')"
                ),
                {"city_id": city.id},
            )


async def test_deleting_a_venue_cascades(session: AsyncSession) -> None:
    venue = await _venue(session, await _city(session, 8, "Testcity"), "Test Venue")
    hall = Hall(venue_id=venue.id, slug="main", name="Main")
    session.add(hall)
    await session.flush()
    session.add_all(
        [
            HallPicture(hall_id=hall.id, storage_key="test/halls/main/01.webp"),
            Recommendation(
                venue_id=venue.id, category=RecommendationCategory.FOOD, name="Test Falafel"
            ),
        ]
    )
    await session.flush()

    await session.execute(delete(Venue).where(Venue.id == venue.id))

    assert await session.scalar(select(func.count()).where(Hall.venue_id == venue.id)) == 0
    assert await session.scalar(select(func.count()).where(HallPicture.hall_id == hall.id)) == 0
    assert (
        await session.scalar(select(func.count()).where(Recommendation.venue_id == venue.id)) == 0
    )


async def test_extras_and_power_filters(session: AsyncSession) -> None:
    venue = await _venue(session, await _city(session, 9, "Testcity"), "Test Venue")
    big = Hall(
        venue_id=venue.id,
        slug="big",
        name="Big",
        stage_width_m=Decimal("24.00"),
        power_circuits_a=[32, 63, 125],
        extras={"green_room": {"value": True, "note": "huge"}},
    )
    small = Hall(
        venue_id=venue.id,
        slug="small",
        name="Small",
        stage_width_m=Decimal("10.00"),
        power_circuits_a=[32],
        extras={"green_room": {"value": False}},
    )
    session.add_all([big, small])
    await session.flush()

    in_venue = Hall.venue_id == venue.id
    with_green_room = await session.scalars(
        select(Hall.slug).where(in_venue, Hall.extras.contains({"green_room": {"value": True}}))
    )
    with_125a = await session.scalars(
        select(Hall.slug).where(in_venue, Hall.power_circuits_a.contains([125]))
    )
    wide_stage = await session.scalars(select(Hall.slug).where(in_venue, Hall.stage_width_m >= 12))

    assert list(with_green_room) == ["big"]
    assert list(with_125a) == ["big"]
    assert list(wide_stage) == ["big"]


@pytest.mark.parametrize(
    ("query", "index_name"),
    [
        (
            'SELECT id FROM halls WHERE extras @> \'{"green_room": {"value": true}}\'',
            "ix_halls_extras",
        ),
        ("SELECT id FROM halls WHERE power_circuits_a @> ARRAY[125]", "ix_halls_power_circuits_a"),
        ("SELECT id FROM venues WHERE name ILIKE '%zap%'", "ix_venues_name_trgm"),
        ("SELECT id FROM halls WHERE capacity_seated >= 500", "ix_halls_capacity_seated"),
    ],
)
async def test_filters_can_use_their_index(
    session: AsyncSession, query: str, index_name: str
) -> None:
    """With few rows Postgres prefers a table scan; disabling it shows the index is usable."""
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join((await session.scalars(text(f"EXPLAIN {query}"))).all())

    assert index_name in plan
