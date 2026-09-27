import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import City, District, LocalityType
from scripts.seed_cities import CityRow, upsert_cities

pytestmark = pytest.mark.anyio

# Codes far outside the real CBS range, so they never clash with seeded cities
ROWS = [
    CityRow(990_101, "Test City", "עיר בדיקה", District.CENTER, LocalityType.CITY),
    CityRow(990_102, "Test Kibbutz", "קיבוץ בדיקה", District.NORTH, LocalityType.KIBBUTZ),
]
TEST_CODES = [row.official_code for row in ROWS]


async def _count(session: AsyncSession) -> int:
    count = await session.scalar(
        select(func.count()).select_from(City).where(City.official_code.in_(TEST_CODES))
    )
    return int(count or 0)


async def test_upsert_is_idempotent_and_updates_names(session: AsyncSession) -> None:
    assert await upsert_cities(session, ROWS) == 2
    assert await upsert_cities(session, ROWS) == 2
    assert await _count(session) == 2

    renamed = [CityRow(990_101, "Test City Renamed", "עיר", District.CENTER, LocalityType.CITY)]
    await upsert_cities(session, renamed)

    city = await session.scalar(select(City).where(City.official_code == 990_101))
    assert city is not None
    await session.refresh(city)
    assert city.name_en == "Test City Renamed"
    assert city.slug == "test-city-renamed"
    assert await _count(session) == 2


async def test_upsert_nothing_is_a_no_op(session: AsyncSession) -> None:
    assert await upsert_cities(session, []) == 0
