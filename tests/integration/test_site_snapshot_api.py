"""The site snapshot against a real database: each part equals the matching public endpoint.

Test rows use unique names ("Zqs ..."), so the tests also pass on a database with real venues.
"""

from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import httpx2
import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import PUBLIC_CACHE_CONTROL
from app.core.config import Settings
from app.db.dependencies import get_session
from app.db.models import (
    City,
    District,
    Hall,
    HallPicture,
    LocalityType,
    Recommendation,
    RecommendationCategory,
    Venue,
    VenuePicture,
    VenueType,
)
from app.main import create_app
from app.services.recommendations import israel_today

pytestmark = pytest.mark.anyio

API = "/api/v1"
SNAPSHOT = f"{API}/site/snapshot"
TODAY = date(2026, 10, 15)


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx2.AsyncClient]:
    settings = Settings(
        _env_file=None,
        environment="ci",
        database_url=None,
        pictures_base_url="https://pictures.example.test",
    )
    app = create_app(settings)

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[israel_today] = lambda: TODAY
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def add_venue(
    session: AsyncSession, city: City, slug: str, *, published: bool = True
) -> tuple[Venue, Hall]:
    """A venue with a published hall, a hall picture, a venue picture and a recommendation."""
    venue = Venue(
        slug=slug,
        name=f"Zqs {slug}",
        name_he="א",
        city_id=city.id,
        venue_type=VenueType.THEATER,
        street_address="1 Zqs St",
        website="https://example.test",
        is_published=published,
    )
    session.add(venue)
    await session.flush()
    hall = Hall(
        venue_id=venue.id,
        slug="main",
        name="Main",
        capacity_seated=300,
        field_notes={"capacity_seated": "A note"},
        is_published=True,
    )
    session.add(hall)
    await session.flush()
    session.add_all(
        [
            HallPicture(hall_id=hall.id, storage_key=f"zqs/{slug}/h1", width=10, height=10),
            VenuePicture(
                venue_id=venue.id, storage_key=f"venue-pictures/zqs-{slug}", width=10, height=10
            ),
            Recommendation(
                venue_id=venue.id, category=RecommendationCategory.FOOD, name="Zqs Place"
            ),
        ]
    )
    await session.flush()
    return venue, hall


@pytest.fixture
async def city(session: AsyncSession) -> City:
    city = City(
        official_code=990_901,
        name_en="Zqs City",
        name_he="ת",
        slug="zqs-city",
        district=District.NORTH,
        locality_type=LocalityType.CITY,
    )
    session.add(city)
    await session.flush()
    return city


async def snapshot_venues(client: httpx2.AsyncClient) -> list[dict[str, Any]]:
    response = await client.get(SNAPSHOT)
    assert response.status_code == 200, response.text
    venues: list[dict[str, Any]] = response.json()["venues"]
    return venues


async def get_json(client: httpx2.AsyncClient, path: str) -> Any:
    response = await client.get(f"{API}{path}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_each_part_equals_the_matching_endpoint(
    client: httpx2.AsyncClient, session: AsyncSession, city: City
) -> None:
    venue, hall = await add_venue(session, city, "zqs-full")
    second = Hall(venue_id=venue.id, slug="a-small", name="A small", is_published=True)
    session.add_all(
        [
            second,
            # Out of id order, so the picture order has to come from display_order
            HallPicture(
                hall_id=hall.id, storage_key="zqs/first", width=10, height=10, display_order=-1
            ),
            # Sponsored places come first in the public list
            Recommendation(
                venue_id=venue.id,
                category=RecommendationCategory.PARKING,
                name="Zqs Sponsored",
                is_sponsored=True,
            ),
        ]
    )
    await session.flush()

    item = next(v for v in await snapshot_venues(client) if v["summary"]["slug"] == "zqs-full")

    base = "/venues/zqs-full"
    assert item["detail"] == await get_json(client, base)
    assert item["pictures"] == await get_json(client, f"{base}/pictures")
    assert item["recommendations"] == await get_json(client, f"{base}/recommendations")
    assert item["recommendations"][0]["name"] == "Zqs Sponsored"
    listed = await get_json(client, "/venues?q=zqs-full")
    assert item["summary"] == listed["items"][0]

    # Same halls, in the order of the venue's hall list
    assert [h["document"]["slug"] for h in item["halls"]] == ["a-small", "main"]
    assert [h["slug"] for h in item["detail"]["halls"]] == ["a-small", "main"]
    for part in item["halls"]:
        path = f"{base}/halls/{part['document']['slug']}"
        assert part["document"] == await get_json(client, path)
        assert part["pictures"] == await get_json(client, f"{path}/pictures")
    assert len(item["halls"][1]["pictures"]) == 2
    assert item["halls"][1]["pictures"][0]["url"].endswith("first/large.webp")


async def test_venues_are_in_the_order_of_the_public_list(
    client: httpx2.AsyncClient, session: AsyncSession, city: City
) -> None:
    await add_venue(session, city, "zqs-b")
    await add_venue(session, city, "zqs-a")

    venues = await snapshot_venues(client)

    slugs = [v["summary"]["slug"] for v in venues]
    assert slugs.index("zqs-a") < slugs.index("zqs-b")
    listed = await get_json(client, f"/venues?limit=100&city={city.slug}")
    ours = [slug for slug in slugs if slug.startswith("zqs-")]
    assert ours == [v["slug"] for v in listed["items"]]


async def test_only_published_and_active_rows_are_included(
    client: httpx2.AsyncClient, session: AsyncSession, city: City
) -> None:
    await add_venue(session, city, "zqs-hidden", published=False)
    venue, _ = await add_venue(session, city, "zqs-shown")
    hidden_hall = Hall(venue_id=venue.id, slug="hidden", name="Hidden", is_published=False)
    session.add_all(
        [
            hidden_hall,
            Recommendation(
                venue_id=venue.id,
                category=RecommendationCategory.COFFEE,
                name="Zqs Closed",
                is_active=False,
            ),
        ]
    )
    await session.flush()

    venues = await snapshot_venues(client)

    slugs = [v["summary"]["slug"] for v in venues]
    assert "zqs-hidden" not in slugs
    item = next(v for v in venues if v["summary"]["slug"] == "zqs-shown")
    assert [h["document"]["slug"] for h in item["halls"]] == ["main"]
    assert [h["slug"] for h in item["detail"]["halls"]] == ["main"]
    assert item["summary"]["hall_count"] == 1
    assert [p["name"] for p in item["recommendations"]] == ["Zqs Place"]


async def test_query_count_does_not_grow_with_the_venues(
    client: httpx2.AsyncClient, session: AsyncSession, city: City
) -> None:
    await add_venue(session, city, "zqs-count-1")
    connection = (await session.connection()).sync_connection
    assert connection is not None
    statements: list[str] = []

    def count(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    await snapshot_venues(client)  # the first read may still load session state
    event.listen(connection, "before_cursor_execute", count)
    try:
        await snapshot_venues(client)
        before = len(statements)
        statements.clear()

        event.remove(connection, "before_cursor_execute", count)
        await add_venue(session, city, "zqs-count-2")
        await add_venue(session, city, "zqs-count-3")
        event.listen(connection, "before_cursor_execute", count)

        await snapshot_venues(client)
    finally:
        event.remove(connection, "before_cursor_execute", count)

    assert len(statements) == before
    assert before <= 5


async def test_snapshot_is_not_stored_by_the_cdn(
    client: httpx2.AsyncClient, session: AsyncSession, city: City
) -> None:
    await add_venue(session, city, "zqs-cache")

    response = await client.get(SNAPSHOT)

    assert response.headers["cache-control"] == PUBLIC_CACHE_CONTROL
