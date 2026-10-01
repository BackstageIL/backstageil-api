"""Admin write API against a real database (rolled back after each test)."""

from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import hash_api_key
from app.db.dependencies import get_session
from app.db.models import City, District, Hall, LocalityType, Venue
from app.main import create_app

pytestmark = pytest.mark.anyio

KEY = "integration-test-admin-key-0123456789"
AUTH = {"X-API-Key": KEY}
ADMIN = "/api/v1/admin"
PUBLIC = "/api/v1"
CITY_CODE = 990_501


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx2.AsyncClient]:
    settings = Settings(
        _env_file=None, environment="ci", database_url=None, admin_api_key_hash=hash_api_key(KEY)
    )
    app = create_app(settings)

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = test_session
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
async def city(session: AsyncSession) -> City:
    city = City(
        official_code=CITY_CODE,
        name_en="Zqa Admin City",
        name_he="ע",
        slug="zqa-admin-city",
        district=District.CENTER,
        locality_type=LocalityType.CITY,
    )
    session.add(city)
    await session.flush()
    return city


def item(slug: str = "zqa-venue", **hall: Any) -> dict[str, Any]:
    return {
        "venue": {
            "slug": slug,
            "name": f"Zqa {slug}",
            "city_code": CITY_CODE,
            "street_address": f"1 {slug} St",
            "venue_type": "culture_hall",
        },
        "hall": {"slug": "main", "name": "Main hall", "capacity_seated": 500} | hall,
    }


async def import_(
    client: httpx2.AsyncClient, items: list[dict[str, Any]], **params: Any
) -> httpx2.Response:
    query = {"publish": "true"} | {k: str(v).lower() for k, v in params.items()}
    return await client.post(f"{ADMIN}/venues/import", params=query, json=items, headers=AUTH)


async def is_public(client: httpx2.AsyncClient, path: str) -> bool:
    return (await client.get(f"{PUBLIC}{path}")).status_code == 200


# --- auth -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/venues/import?publish=true"),
        ("GET", "/venues"),
        ("GET", "/venues/x"),
        ("GET", "/venues/x/halls/main"),
        ("PATCH", "/venues/x"),
        ("PATCH", "/venues/x/halls/main"),
        ("POST", "/venues/x/publish"),
        ("POST", "/venues/x/unpublish"),
        ("POST", "/venues/x/halls/main/publish"),
        ("POST", "/venues/x/halls/main/unpublish"),
        ("DELETE", "/venues/x?confirm=x"),
        ("DELETE", "/venues/x/halls/main?confirm=main"),
    ],
)
async def test_every_admin_route_requires_the_key(
    client: httpx2.AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, f"{ADMIN}{path}", json=[])

    assert response.status_code == 401


# --- import -----------------------------------------------------------------------------------


async def test_dry_run_counts_but_writes_nothing(
    client: httpx2.AsyncClient, city: City, session: AsyncSession
) -> None:
    response = await import_(client, [item()], dry_run=True)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "items": 1,
        "venues_created": 1,
        "venues_updated": 0,
        "halls_created": 1,
        "halls_updated": 0,
        "dry_run": True,
    }
    assert await session.scalar(select(func.count()).where(Venue.slug == "zqa-venue")) == 0


async def test_import_then_reimport_updates_without_duplicates(
    client: httpx2.AsyncClient, city: City, session: AsyncSession
) -> None:
    first = (await import_(client, [item()])).json()
    second = (await import_(client, [item(capacity_seated=650)])).json()

    assert (first["venues_created"], first["halls_created"]) == (1, 1)
    assert (second["venues_updated"], second["halls_updated"]) == (1, 1)
    assert await session.scalar(select(func.count()).where(Venue.slug == "zqa-venue")) == 1
    hall = (await client.get(f"{PUBLIC}/venues/zqa-venue/halls/main")).json()
    assert hall["capacity_seated"] == 650


async def test_upload_decides_visibility(client: httpx2.AsyncClient, city: City) -> None:
    await import_(client, [item()], publish=True)
    assert await is_public(client, "/venues/zqa-venue")

    await import_(client, [item()], publish=False)
    assert not await is_public(client, "/venues/zqa-venue")


async def test_publish_parameter_is_required(client: httpx2.AsyncClient, city: City) -> None:
    response = await client.post(f"{ADMIN}/venues/import", json=[item()], headers=AUTH)

    assert response.status_code == 422


async def test_duplicate_slugs_are_rejected(client: httpx2.AsyncClient, city: City) -> None:
    response = await import_(client, [item(), item()])

    assert response.status_code == 422
    assert response.json()["error_code"] == "DUPLICATE_SLUGS"


async def test_unknown_city_rejects_the_whole_batch(
    client: httpx2.AsyncClient, city: City, session: AsyncSession
) -> None:
    bad = item("zqa-bad")
    bad["venue"]["city_code"] = 990_599
    response = await import_(client, [item("zqa-good"), bad])

    assert response.status_code == 422
    assert response.json()["error_code"] == "UNKNOWN_CITY"
    count = await session.scalar(
        select(func.count()).where(Venue.slug.in_(["zqa-good", "zqa-bad"]))
    )
    assert count == 0


async def test_too_many_items_are_rejected(client: httpx2.AsyncClient, city: City) -> None:
    response = await import_(client, [item(f"zqa-v{i}") for i in range(201)])

    assert response.status_code == 422


# --- edit -------------------------------------------------------------------------------------


async def test_patch_venue_changes_only_sent_fields(client: httpx2.AsyncClient, city: City) -> None:
    await import_(client, [item()])

    response = await client.patch(
        f"{ADMIN}/venues/zqa-venue", json={"name": "Zqa Renamed"}, headers=AUTH
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Zqa Renamed"
    assert body["street_address"] == "1 zqa-venue St"  # untouched
    assert (await client.get(f"{PUBLIC}/venues/zqa-venue")).json()["name"] == "Zqa Renamed"


@pytest.mark.parametrize(
    "patch", [{"unknown": 1}, {"name": "call 052-1234567"}, {"city_code": 990_599}]
)
async def test_invalid_venue_patch_is_422(
    client: httpx2.AsyncClient, city: City, patch: dict[str, Any]
) -> None:
    await import_(client, [item()])

    response = await client.patch(f"{ADMIN}/venues/zqa-venue", json=patch, headers=AUTH)

    assert response.status_code == 422


async def test_patch_hall_partial_null_and_map_replacement(
    client: httpx2.AsyncClient, city: City, session: AsyncSession
) -> None:
    await import_(
        client,
        [
            item(
                grid_height_m=12,
                has_green_room=True,
                field_notes={"grid_height_m": "old note"},
                extras={"stage_cameras": {"label": "Stage cameras", "value": True}},
            )
        ],
    )
    before = await session.scalar(
        select(Hall.updated_at).join(Venue).where(Venue.slug == "zqa-venue")
    )

    response = await client.patch(
        f"{ADMIN}/venues/zqa-venue/halls/main",
        json={
            "capacity_seated": 777,
            "has_green_room": None,
            "field_notes": {"capacity_seated": "new note"},
        },
        headers=AUTH,
    )

    assert response.status_code == 200
    hall = response.json()
    assert hall["capacity_seated"] == 777
    assert hall["has_green_room"] is None  # explicit null clears
    assert hall["grid_height_m"] == 12.0  # not sent: kept
    assert hall["field_notes"] == {"capacity_seated": "new note"}  # replaced
    assert hall["extras"] == {"stage_cameras": {"label": "Stage cameras", "value": True}}  # kept
    assert hall["is_published"] is True  # edits don't change visibility
    after = await session.scalar(
        select(Hall.updated_at).join(Venue).where(Venue.slug == "zqa-venue")
    )
    assert before is not None and after is not None and after >= before


@pytest.mark.parametrize(
    "patch",
    [
        {"extras": {"has_green_room": {"value": True}}},  # fixed column as extra
        {"extras": {"stage_cameras": {"value": True}}},  # unregistered extra without label
        {"notes": "ask 052-1234567"},
        {"capacity_seated": -5},
        {"not_a_field": 1},
    ],
)
async def test_invalid_hall_patch_is_422(
    client: httpx2.AsyncClient, city: City, patch: dict[str, Any]
) -> None:
    await import_(client, [item()])

    response = await client.patch(f"{ADMIN}/venues/zqa-venue/halls/main", json=patch, headers=AUTH)

    assert response.status_code == 422


# --- visibility -------------------------------------------------------------------------------


async def test_publish_and_unpublish(client: httpx2.AsyncClient, city: City) -> None:
    await import_(client, [item()], publish=False)
    admin_view = (await client.get(f"{ADMIN}/venues/zqa-venue", headers=AUTH)).json()
    assert admin_view["is_published"] is False

    state = await client.post(f"{ADMIN}/venues/zqa-venue/publish", headers=AUTH)
    assert state.json() == {"slug": "zqa-venue", "is_published": True}
    # the hall was uploaded unpublished: the venue is public, the hall not yet
    assert await is_public(client, "/venues/zqa-venue")
    assert not await is_public(client, "/venues/zqa-venue/halls/main")

    await client.post(f"{ADMIN}/venues/zqa-venue/halls/main/publish", headers=AUTH)
    assert await is_public(client, "/venues/zqa-venue/halls/main")

    await client.post(f"{ADMIN}/venues/zqa-venue/unpublish", headers=AUTH)
    assert not await is_public(client, "/venues/zqa-venue")
    assert not await is_public(client, "/venues/zqa-venue/halls/main")  # hidden with its venue

    hall_admin = (await client.get(f"{ADMIN}/venues/zqa-venue/halls/main", headers=AUTH)).json()
    assert hall_admin["is_published"] is True


async def test_admin_list_includes_unpublished_and_filters(
    client: httpx2.AsyncClient, city: City
) -> None:
    await import_(client, [item("zqa-shown")], publish=True)
    await import_(client, [item("zqa-hidden")], publish=False)

    all_rows = (await client.get(f"{ADMIN}/venues", params={"q": "zqa"}, headers=AUTH)).json()
    hidden = (
        await client.get(f"{ADMIN}/venues", params={"q": "zqa", "published": "false"}, headers=AUTH)
    ).json()

    assert {v["slug"]: v["is_published"] for v in all_rows["items"]} == {
        "zqa-hidden": False,
        "zqa-shown": True,
    }
    assert [v["slug"] for v in hidden["items"]] == ["zqa-hidden"]


# --- delete -----------------------------------------------------------------------------------


@pytest.mark.parametrize("confirm", [None, "wrong"])
async def test_delete_needs_confirmation(
    client: httpx2.AsyncClient, city: City, confirm: str | None
) -> None:
    await import_(client, [item()])
    params = {"confirm": confirm} if confirm else {}

    response = await client.delete(f"{ADMIN}/venues/zqa-venue", params=params, headers=AUTH)

    assert response.status_code == 422
    assert response.json()["error_code"] == "CONFIRMATION_MISMATCH"
    assert await is_public(client, "/venues/zqa-venue")


async def test_delete_venue_cascades(
    client: httpx2.AsyncClient, city: City, session: AsyncSession
) -> None:
    await import_(client, [item()])

    response = await client.delete(
        f"{ADMIN}/venues/zqa-venue", params={"confirm": "zqa-venue"}, headers=AUTH
    )

    assert response.status_code == 204
    assert await session.scalar(select(func.count()).where(Venue.slug == "zqa-venue")) == 0
    halls_left = await session.scalar(
        select(func.count()).select_from(Hall).join(Venue).where(Venue.slug == "zqa-venue")
    )
    assert halls_left == 0
    again = await client.delete(
        f"{ADMIN}/venues/zqa-venue", params={"confirm": "zqa-venue"}, headers=AUTH
    )
    assert again.status_code == 404


async def test_delete_hall_keeps_the_venue(client: httpx2.AsyncClient, city: City) -> None:
    await import_(client, [item()])

    response = await client.delete(
        f"{ADMIN}/venues/zqa-venue/halls/main", params={"confirm": "main"}, headers=AUTH
    )

    assert response.status_code == 204
    venue = (await client.get(f"{ADMIN}/venues/zqa-venue", headers=AUTH)).json()
    assert venue["halls"] == []
