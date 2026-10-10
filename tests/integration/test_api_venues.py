"""Public venue/hall/city endpoints against a real database (rolled back after each test).

Test rows use unique names ("Zqx ...") and their own cities, so the tests also pass on a
database that already contains real venues (Neon dev).
"""

from collections.abc import AsyncIterator
from decimal import Decimal

import httpx2
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import PUBLIC_CACHE_CONTROL
from app.core.config import Settings
from app.db.dependencies import get_session
from app.db.models import City, District, Hall, LocalityType, Venue, VenueType
from app.main import create_app

pytestmark = pytest.mark.anyio

API = "/api/v1"


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx2.AsyncClient]:
    app = create_app(Settings(_env_file=None, environment="ci", database_url=None))

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = test_session
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
async def data(session: AsyncSession) -> dict[str, City]:
    center = City(
        official_code=990_401,
        name_en="Zqx Center City",
        name_he="א",
        slug="zqx-center-city",
        district=District.CENTER,
        locality_type=LocalityType.CITY,
    )
    north = City(
        official_code=990_402,
        name_en="Zqx North Kibbutz",
        name_he="ב",
        slug="zqx-north-kibbutz",
        district=District.NORTH,
        locality_type=LocalityType.KIBBUTZ,
    )
    session.add_all([center, north])
    await session.flush()

    alpha = Venue(
        slug="zqx-alpha",
        name="Zqx Alpha Hall",
        city_id=center.id,
        venue_type=VenueType.CULTURE_HALL,
        is_published=True,
    )
    beta = Venue(
        slug="zqx-beta",
        name="Zqx Beta Club",
        city_id=north.id,
        venue_type=VenueType.CLUB,
        is_published=True,
    )
    hidden = Venue(
        slug="zqx-hidden",
        name="Zqx Hidden Venue",
        city_id=center.id,
        venue_type=VenueType.CULTURE_HALL,
        is_published=False,
    )
    session.add_all([alpha, beta, hidden])
    await session.flush()

    session.add_all(
        [
            Hall(
                venue_id=alpha.id,
                slug="main",
                name="Main hall",
                is_published=True,
                capacity_seated=800,
                stage_width_m=Decimal("24.00"),
                stage_depth_m=Decimal("12.5"),
                power_circuits_a=[32, 63, 125],
                pa_flying_possible=True,
                house_pa="Test PA",
                field_notes={"stage_width_m": "Measured at the proscenium line"},
                extras={"stage_cameras": {"label": "Stage cameras", "value": True}},
            ),
            Hall(venue_id=alpha.id, slug="draft", name="Draft hall", is_published=False),
            Hall(venue_id=beta.id, slug="main", name="Club floor", is_published=True),
            Hall(venue_id=hidden.id, slug="main", name="Hidden hall", is_published=True),
        ]
    )
    await session.flush()
    return {"center": center, "north": north}


async def test_list_returns_only_published_venues_sorted_with_hall_counts(
    client: httpx2.AsyncClient, data: dict[str, City]
) -> None:
    response = await client.get(f"{API}/venues", params={"q": "zqx"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert [v["slug"] for v in body["items"]] == ["zqx-alpha", "zqx-beta"]
    alpha = body["items"][0]
    assert alpha["hall_count"] == 1  # the unpublished draft hall is not counted
    assert alpha["city"] == {
        "slug": "zqx-center-city",
        "name_en": "Zqx Center City",
        "name_he": "א",
        "district": "center",
    }
    assert alpha["name_he"] is None  # not filled yet


async def test_search_is_case_insensitive(
    client: httpx2.AsyncClient, data: dict[str, City]
) -> None:
    response = await client.get(f"{API}/venues", params={"q": "ZQX BETA"})

    assert [v["slug"] for v in response.json()["items"]] == ["zqx-beta"]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"city": "zqx-north-kibbutz"}, ["zqx-beta"]),
        ({"q": "zqx", "district": "center"}, ["zqx-alpha"]),
        ({"q": "zqx", "type": "club"}, ["zqx-beta"]),
        ({"city": "zqx-center-city", "type": "club"}, []),
    ],
)
async def test_filters(
    client: httpx2.AsyncClient, data: dict[str, City], params: dict[str, str], expected: list[str]
) -> None:
    response = await client.get(f"{API}/venues", params=params)

    assert [v["slug"] for v in response.json()["items"]] == expected


async def test_pagination(client: httpx2.AsyncClient, data: dict[str, City]) -> None:
    first = (await client.get(f"{API}/venues", params={"q": "zqx", "limit": 1})).json()
    second = (
        await client.get(f"{API}/venues", params={"q": "zqx", "limit": 1, "offset": 1})
    ).json()

    assert (first["total"], first["limit"], first["offset"]) == (2, 1, 0)
    assert [v["slug"] for v in first["items"]] == ["zqx-alpha"]
    assert [v["slug"] for v in second["items"]] == ["zqx-beta"]


async def test_venue_detail_lists_published_halls_only(
    client: httpx2.AsyncClient, data: dict[str, City]
) -> None:
    response = await client.get(f"{API}/venues/zqx-alpha")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Zqx Alpha Hall"
    assert body["halls"] == [
        {
            "slug": "main",
            "name": "Main hall",
            "name_he": None,
            "capacity_seated": 800,
            "stage_width_m": 24.0,
            "stage_depth_m": 12.5,
        }
    ]


async def test_hall_document(client: httpx2.AsyncClient, data: dict[str, City]) -> None:
    response = await client.get(f"{API}/venues/zqx-alpha/halls/main")

    assert response.status_code == 200
    body = response.json()
    assert body["venue"]["slug"] == "zqx-alpha"
    assert body["venue"]["city"]["slug"] == "zqx-center-city"
    assert body["stage_width_m"] == 24.0  # a JSON number, not "24.00"
    assert body["power_circuits_a"] == [32, 63, 125]
    assert body["pa_flying_possible"] is True
    assert body["has_green_room"] is None  # unknown stays null
    assert body["house_pa"] == "Test PA"
    assert body["field_notes"] == {"stage_width_m": "Measured at the proscenium line"}
    assert body["extras"] == {"stage_cameras": {"label": "Stage cameras", "value": True}}


@pytest.mark.parametrize(
    ("path", "error_code"),
    [
        ("/venues/zqx-nothing", "VENUE_NOT_FOUND"),
        ("/venues/zqx-hidden", "VENUE_NOT_FOUND"),  # unpublished venue
        ("/venues/zqx-alpha/halls/nothing", "HALL_NOT_FOUND"),
        ("/venues/zqx-alpha/halls/draft", "HALL_NOT_FOUND"),  # unpublished hall
        ("/venues/zqx-hidden/halls/main", "HALL_NOT_FOUND"),  # published hall, hidden venue
    ],
)
async def test_not_found(
    client: httpx2.AsyncClient, data: dict[str, City], path: str, error_code: str
) -> None:
    response = await client.get(f"{API}{path}")

    assert response.status_code == 404
    assert response.json()["error_code"] == error_code
    assert "cache-control" not in response.headers


async def test_cities_lists_only_cities_with_published_venues(
    client: httpx2.AsyncClient, data: dict[str, City]
) -> None:
    response = await client.get(f"{API}/cities")

    assert response.status_code == 200
    test_cities = {c["slug"]: c for c in response.json() if c["slug"].startswith("zqx-")}
    # center city: alpha published + hidden unpublished -> 1; north: beta -> 1
    assert test_cities["zqx-center-city"]["venue_count"] == 1
    assert test_cities["zqx-north-kibbutz"]["venue_count"] == 1
    assert test_cities["zqx-north-kibbutz"]["district"] == "north"


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
        {"q": "a"},
        {"district": "mars"},
        {"type": "stadium"},
        {"city": "Not A Slug"},
    ],
)
async def test_invalid_query_is_422(
    client: httpx2.AsyncClient, data: dict[str, City], params: dict[str, str | int]
) -> None:
    response = await client.get(f"{API}/venues", params=params)

    assert response.status_code == 422
    assert "cache-control" not in response.headers


@pytest.mark.parametrize(
    "path", ["/venues?q=zqx", "/venues/zqx-alpha", "/venues/zqx-alpha/halls/main", "/cities"]
)
async def test_successful_responses_are_cacheable(
    client: httpx2.AsyncClient, data: dict[str, City], path: str
) -> None:
    response = await client.get(f"{API}{path}")

    assert response.status_code == 200
    assert response.headers["cache-control"] == PUBLIC_CACHE_CONTROL
    # Never stored by the CDN: site rebuilds must read fresh data (BSIL-53)
    assert "s-maxage" not in PUBLIC_CACHE_CONTROL
    assert "stale-while-revalidate" not in PUBLIC_CACHE_CONTROL
