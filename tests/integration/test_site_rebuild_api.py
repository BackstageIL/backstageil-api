"""Admin writes against a real database trigger exactly one website rebuild each (BSIL-46)."""

from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import SiteRebuildFailedError
from app.core.security import hash_api_key
from app.db.dependencies import get_session
from app.db.models import City, District, LocalityType
from app.main import create_app

pytestmark = pytest.mark.anyio

KEY = "integration-test-admin-key-0123456789"
AUTH = {"X-API-Key": KEY}
ADMIN = "/api/v1/admin"
CITY_CODE = 990_801


class CountingRebuilder:
    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    async def trigger(self) -> None:
        self.calls += 1
        if self.fail:
            raise SiteRebuildFailedError()


@pytest.fixture
def rebuilder() -> CountingRebuilder:
    return CountingRebuilder()


@pytest.fixture
async def client(
    session: AsyncSession, rebuilder: CountingRebuilder
) -> AsyncIterator[httpx2.AsyncClient]:
    settings = Settings(
        _env_file=None, environment="ci", database_url=None, admin_api_key_hash=hash_api_key(KEY)
    )
    app = create_app(settings)
    app.state.site_rebuilder = rebuilder

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
        name_en="Zqs Rebuild City",
        name_he="ש",
        slug="zqs-rebuild-city",
        district=District.SOUTH,
        locality_type=LocalityType.CITY,
    )
    session.add(city)
    await session.flush()
    return city


def item() -> dict[str, Any]:
    return {
        "venue": {
            "slug": "zqs-venue",
            "name": "Zqs Venue",
            "city_code": CITY_CODE,
            "venue_type": "club",
        },
        "hall": {"slug": "main", "name": "Main hall"},
    }


async def test_each_successful_write_rebuilds_once(
    client: httpx2.AsyncClient, city: City, rebuilder: CountingRebuilder
) -> None:
    steps: list[tuple[str, str, dict[str, Any]]] = [
        ("POST", "/venues/import", {"params": {"publish": "true"}, "json": [item()]}),
        ("PATCH", "/venues/zqs-venue", {"json": {"name": "Zqs Renamed"}}),
        ("PATCH", "/venues/zqs-venue/halls/main", {"json": {"capacity_seated": 300}}),
        ("POST", "/venues/zqs-venue/unpublish", {}),
        ("POST", "/venues/zqs-venue/publish", {}),
        (
            "POST",
            "/venues/zqs-venue/recommendations",
            {"json": {"category": "food", "name": "Zqs Food"}},
        ),
        ("DELETE", "/venues/zqs-venue/halls/main", {"params": {"confirm": "main"}}),
        ("DELETE", "/venues/zqs-venue", {"params": {"confirm": "zqs-venue"}}),
    ]
    for count, (method, path, kwargs) in enumerate(steps, start=1):
        response = await client.request(method, f"{ADMIN}{path}", headers=AUTH, **kwargs)
        assert response.status_code < 300, (path, response.text)
        assert rebuilder.calls == count, path


async def test_reads_dry_runs_and_rejected_writes_do_not_rebuild(
    client: httpx2.AsyncClient, city: City, rebuilder: CountingRebuilder
) -> None:
    dry = await client.post(
        f"{ADMIN}/venues/import",
        params={"publish": "true", "dry_run": "true"},
        json=[item()],
        headers=AUTH,
    )
    read = await client.get(f"{ADMIN}/venues", headers=AUTH)
    invalid = await client.patch(f"{ADMIN}/venues/zqs-nope", json={"name": "Xy"}, headers=AUTH)
    unauthorized = await client.post(
        f"{ADMIN}/venues/import", params={"publish": "true"}, json=[item()]
    )

    assert (dry.status_code, read.status_code) == (200, 200)
    assert (invalid.status_code, unauthorized.status_code) == (404, 401)
    assert rebuilder.calls == 0


async def test_rebuild_failure_still_returns_the_saved_change(
    client: httpx2.AsyncClient, city: City, rebuilder: CountingRebuilder
) -> None:
    rebuilder.fail = True

    response = await client.post(
        f"{ADMIN}/venues/import", params={"publish": "true"}, json=[item()], headers=AUTH
    )

    assert response.status_code == 200
    assert response.json()["venues_created"] == 1
    assert rebuilder.calls == 1
    assert (await client.get("/api/v1/venues/zqs-venue")).status_code == 200
