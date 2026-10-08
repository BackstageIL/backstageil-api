"""Venue recommendations API (admin create/edit/delete, public list) against a real database."""

from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import PUBLIC_CACHE_CONTROL
from app.core.config import Settings
from app.core.security import hash_api_key
from app.db.dependencies import get_session
from app.db.models import City, District, LocalityType, Venue, VenueType
from app.main import create_app
from app.services.recommendations import israel_today

pytestmark = pytest.mark.anyio

KEY = "integration-test-admin-key-0123456789"
AUTH = {"X-API-Key": KEY}
TODAY = date(2026, 10, 15)
ADMIN = "/api/v1/admin/venues/zqr-venue/recommendations"
PUBLIC = "/api/v1/venues/zqr-venue/recommendations"


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx2.AsyncClient]:
    settings = Settings(
        _env_file=None, environment="ci", database_url=None, admin_api_key_hash=hash_api_key(KEY)
    )
    app = create_app(settings)

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[israel_today] = lambda: TODAY
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
async def venue(session: AsyncSession) -> Venue:
    city = City(
        official_code=990_701,
        name_en="Zqr Recommendation City",
        name_he="ר",
        slug="zqr-city",
        district=District.HAIFA,
        locality_type=LocalityType.CITY,
    )
    session.add(city)
    await session.flush()
    venue = Venue(
        slug="zqr-venue",
        name="Zqr Venue",
        city_id=city.id,
        venue_type=VenueType.CLUB,
        is_published=True,
    )
    session.add(venue)
    await session.flush()
    return venue


async def add(client: httpx2.AsyncClient, **fields: Any) -> dict[str, Any]:
    body = {"category": "food", "name": "Zqr Place"} | fields
    response = await client.post(ADMIN, json=body, headers=AUTH)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


async def public_names(client: httpx2.AsyncClient, **params: str) -> list[str]:
    response = await client.get(PUBLIC, params=params)
    assert response.status_code == 200
    return [item["name"] for item in response.json()]


# --- auth -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"), [("GET", ""), ("POST", ""), ("PATCH", "/1"), ("DELETE", "/1")]
)
async def test_admin_routes_require_the_key(
    client: httpx2.AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, f"{ADMIN}{path}", json={})

    assert response.status_code == 401


# --- create and public list -----------------------------------------------------------------------


async def test_create_returns_admin_view(client: httpx2.AsyncClient, venue: Venue) -> None:
    created = await add(
        client,
        category="coffee",
        name="Zqr Espresso Bar",
        address="12 Harbour St",
        website="https://espresso.example.com",
        phone="+972 4-123 4567",
        note="Opens at 6:00, takes large crew orders",
        distance_m=250,
    )

    assert created["category"] == "coffee"
    assert created["website"] == "https://espresso.example.com/"
    assert created["phone"] == "+972 4-123 4567"
    assert created["is_active"] is True
    assert created["is_sponsored"] is False
    assert created["sponsored_now"] is False
    assert created["display_order"] == 0
    assert created["created_at"] and created["updated_at"]


async def test_public_list_shows_active_places_with_public_fields(
    client: httpx2.AsyncClient, venue: Venue
) -> None:
    await add(client, name="Zqr Shown", distance_m=100)
    await add(client, name="Zqr Hidden", is_active=False)

    response = await client.get(PUBLIC)

    assert response.status_code == 200
    assert response.headers["cache-control"] == PUBLIC_CACHE_CONTROL
    (item,) = response.json()
    assert item["name"] == "Zqr Shown"
    assert set(item) == {
        "id",
        "category",
        "name",
        "address",
        "website",
        "phone",
        "note",
        "distance_m",
        "is_sponsored",
    }


async def test_sponsored_first_then_display_order_then_name(
    client: httpx2.AsyncClient, venue: Venue
) -> None:
    await add(client, name="Zqr B", display_order=1)
    await add(client, name="Zqr A", display_order=1)
    await add(client, name="Zqr First by order", display_order=0)
    await add(client, name="Zqr Sponsored", display_order=9, is_sponsored=True)

    assert await public_names(client) == [
        "Zqr Sponsored",
        "Zqr First by order",
        "Zqr A",
        "Zqr B",
    ]


@pytest.mark.parametrize(
    ("sponsored_until", "running"),
    [(None, True), (TODAY, True), (date(2026, 12, 31), True), (date(2026, 10, 14), False)],
)
async def test_sponsorship_runs_until_the_end_of_its_last_day(
    client: httpx2.AsyncClient, venue: Venue, sponsored_until: date | None, running: bool
) -> None:
    await add(client, name="Zqr Regular")
    until = sponsored_until.isoformat() if sponsored_until else None
    created = await add(
        client, name="Zqr Sponsor", display_order=5, is_sponsored=True, sponsored_until=until
    )

    items = (await client.get(PUBLIC)).json()

    assert created["sponsored_now"] is running
    assert items[0]["name"] == ("Zqr Sponsor" if running else "Zqr Regular")
    sponsor = next(i for i in items if i["name"] == "Zqr Sponsor")
    assert sponsor["is_sponsored"] is running


async def test_category_filter(client: httpx2.AsyncClient, venue: Venue) -> None:
    await add(client, category="parking", name="Zqr Parking")
    await add(client, category="hotel", name="Zqr Hotel")

    assert await public_names(client, category="parking") == ["Zqr Parking"]
    assert (await client.get(PUBLIC, params={"category": "spa"})).status_code == 422


async def test_unpublished_venue_has_no_public_list(
    client: httpx2.AsyncClient, venue: Venue, session: AsyncSession
) -> None:
    await add(client)
    venue.is_published = False
    await session.flush()

    response = await client.get(PUBLIC)

    assert response.status_code == 404
    assert response.json()["error_code"] == "VENUE_NOT_FOUND"
    assert len((await client.get(ADMIN, headers=AUTH)).json()) == 1  # admin still sees it


async def test_admin_list_includes_inactive(client: httpx2.AsyncClient, venue: Venue) -> None:
    await add(client, name="Zqr Active")
    await add(client, name="Zqr Inactive", is_active=False)

    items = (await client.get(ADMIN, headers=AUTH)).json()

    assert {i["name"]: i["is_active"] for i in items} == {
        "Zqr Active": True,
        "Zqr Inactive": False,
    }


async def test_create_for_unknown_venue_is_404(client: httpx2.AsyncClient, venue: Venue) -> None:
    response = await client.post(
        "/api/v1/admin/venues/zqr-nope/recommendations",
        json={"category": "food", "name": "Zqr Place"},
        headers=AUTH,
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    "fields",
    [
        {"name": "Call 052-1234567"},  # phone number outside the phone field
        {"note": "ask for dana@example.com"},
        {"address": "x" * 201},
        {"phone": "call me"},
        {"phone": "12"},
        {"website": "not a url"},
        {"website": "https://example.com/" + "a" * 300},
        {"distance_m": -1},
        {"display_order": 40000},
        {"category": "spa"},
        {"unknown": 1},
    ],
)
async def test_invalid_create_is_422(
    client: httpx2.AsyncClient, venue: Venue, fields: dict[str, Any]
) -> None:
    body = {"category": "food", "name": "Zqr Place"} | fields

    response = await client.post(ADMIN, json=body, headers=AUTH)

    assert response.status_code == 422


# --- edit and delete ------------------------------------------------------------------------------


async def test_patch_changes_only_sent_fields_and_clears_nulls(
    client: httpx2.AsyncClient, venue: Venue
) -> None:
    created = await add(
        client, name="Zqr Old", address="1 Old St", website="https://old.example.com", note="Note"
    )

    response = await client.patch(
        f"{ADMIN}/{created['id']}",
        json={"name": "Zqr New", "website": None, "is_sponsored": True},
        headers=AUTH,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Zqr New"
    assert body["website"] is None  # explicit null clears
    assert body["address"] == "1 Old St"  # not sent: kept
    assert body["sponsored_now"] is True
    assert body["updated_at"] >= created["updated_at"]


async def test_deactivate_hides_from_public(client: httpx2.AsyncClient, venue: Venue) -> None:
    created = await add(client, name="Zqr Place")

    await client.patch(f"{ADMIN}/{created['id']}", json={"is_active": False}, headers=AUTH)

    assert await public_names(client) == []


@pytest.mark.parametrize(
    "patch",
    [
        {"name": None},
        {"category": None},
        {"is_active": None},
        {"display_order": None},
        {"phone": "not a phone"},
        {"note": "call 03-5551234"},
        {"venue_id": 1},
    ],
)
async def test_invalid_patch_is_422(
    client: httpx2.AsyncClient, venue: Venue, patch: dict[str, Any]
) -> None:
    created = await add(client)

    response = await client.patch(f"{ADMIN}/{created['id']}", json=patch, headers=AUTH)

    assert response.status_code == 422


async def test_recommendation_of_another_venue_is_404(
    client: httpx2.AsyncClient, venue: Venue, session: AsyncSession
) -> None:
    created = await add(client)
    session.add(
        Venue(
            slug="zqr-other",
            name="Zqr Other",
            city_id=venue.city_id,
            venue_type=VenueType.CLUB,
            is_published=True,
        )
    )
    await session.flush()

    other = "/api/v1/admin/venues/zqr-other/recommendations"
    response = await client.patch(f"{other}/{created['id']}", json={"name": "X y"}, headers=AUTH)

    assert response.status_code == 404
    assert response.json()["error_code"] == "RECOMMENDATION_NOT_FOUND"


async def test_delete(client: httpx2.AsyncClient, venue: Venue) -> None:
    created = await add(client)

    response = await client.delete(f"{ADMIN}/{created['id']}", headers=AUTH)

    assert response.status_code == 204
    assert await public_names(client) == []
    again = await client.delete(f"{ADMIN}/{created['id']}", headers=AUTH)
    assert again.status_code == 404
