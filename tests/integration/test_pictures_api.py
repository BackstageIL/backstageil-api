"""Hall pictures API (admin upload/edit/delete, public gallery) against a real database.

Files go to an in-memory storage instead of Vercel Blob; rows are rolled back after each test.
"""

from collections.abc import AsyncIterator, Sequence
from io import BytesIO
from typing import Any

import httpx2
import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import PUBLIC_CACHE_CONTROL
from app.core.config import Settings
from app.core.exceptions import PictureStorageUnavailableError
from app.core.security import hash_api_key
from app.db.dependencies import get_session
from app.db.models import City, District, Hall, HallPicture, LocalityType, Venue, VenueType
from app.main import create_app
from app.services import pictures
from app.services.picture_storage import get_optional_picture_storage, get_picture_storage

pytestmark = pytest.mark.anyio

KEY = "integration-test-admin-key-0123456789"
AUTH = {"X-API-Key": KEY}
BASE_URL = "https://pictures.example.test"
HALL = "/venues/zqp-venue/halls/main/pictures"
ADMIN = f"/api/v1/admin{HALL}"
PUBLIC = f"/api/v1{HALL}"


class MemoryStorage:
    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}
        self.fail = False

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        if self.fail:
            raise PictureStorageUnavailableError()
        self.files[key] = (data, content_type)

    async def delete(self, keys: Sequence[str]) -> None:
        if self.fail:
            raise PictureStorageUnavailableError()
        for key in keys:
            self.files.pop(key, None)


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


def make_client(
    session: AsyncSession, storage: MemoryStorage | None, base_url: str | None = BASE_URL
) -> httpx2.AsyncClient:
    settings = Settings(
        _env_file=None,
        environment="ci",
        database_url=None,
        admin_api_key_hash=hash_api_key(KEY),
        pictures_base_url=base_url,
    )
    app = create_app(settings)

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = test_session
    if storage is not None:
        app.dependency_overrides[get_picture_storage] = lambda: storage
        app.dependency_overrides[get_optional_picture_storage] = lambda: storage
    return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def client(
    session: AsyncSession, storage: MemoryStorage
) -> AsyncIterator[httpx2.AsyncClient]:
    async with make_client(session, storage) as http:
        yield http


@pytest.fixture
async def hall(session: AsyncSession) -> Hall:
    city = City(
        official_code=990_601,
        name_en="Zqp Picture City",
        name_he="פ",
        slug="zqp-picture-city",
        district=District.NORTH,
        locality_type=LocalityType.CITY,
    )
    session.add(city)
    await session.flush()
    venue = Venue(
        slug="zqp-venue",
        name="Zqp Venue",
        city_id=city.id,
        venue_type=VenueType.CULTURE_HALL,
        is_published=True,
    )
    session.add(venue)
    await session.flush()
    hall = Hall(venue_id=venue.id, slug="main", name="Main hall", is_published=True)
    session.add(hall)
    await session.flush()
    return hall


def jpeg(color: str = "red", size: tuple[int, int] = (2000, 1000)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, "JPEG")
    return buffer.getvalue()


async def upload(
    client: httpx2.AsyncClient, data: bytes, caption: str | None = None, **kwargs: Any
) -> httpx2.Response:
    form = {"caption": caption} if caption is not None else {}
    return await client.post(
        ADMIN,
        files={"file": ("photo.jpg", data, "image/jpeg")},
        data=form,
        headers=AUTH,
        **kwargs,
    )


# --- auth ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", ""), ("POST", ""), ("PATCH", "/1"), ("DELETE", "/1")],
)
async def test_admin_picture_routes_require_the_key(
    client: httpx2.AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, f"{ADMIN}{path}")

    assert response.status_code == 401


# --- upload -------------------------------------------------------------------------------------


async def test_upload_stores_webp_files_and_a_row(
    client: httpx2.AsyncClient, hall: Hall, storage: MemoryStorage
) -> None:
    response = await upload(client, jpeg(), caption="Stage from the house")

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    key = body["storage_key"]
    assert key.startswith("pictures/")
    assert body["caption"] == "Stage from the house"
    assert (body["width"], body["height"]) == (1600, 800)
    assert body["display_order"] == 0
    assert body["url"] == f"{BASE_URL}/{key}/large.webp"
    assert body["thumbnail_url"] == f"{BASE_URL}/{key}/thumb.webp"
    assert set(storage.files) == {f"{key}/large.webp", f"{key}/thumb.webp"}
    assert {content_type for _, content_type in storage.files.values()} == {"image/webp"}


async def test_public_gallery_lists_in_display_order(
    client: httpx2.AsyncClient, hall: Hall
) -> None:
    first = (await upload(client, jpeg("red"))).json()
    second = (await upload(client, jpeg("blue"), caption="Loading dock")).json()
    assert second["display_order"] == 1  # new pictures go last

    response = await client.get(PUBLIC)

    assert response.status_code == 200
    assert response.headers["cache-control"] == PUBLIC_CACHE_CONTROL
    gallery = response.json()
    assert [p["id"] for p in gallery] == [first["id"], second["id"]]
    assert set(gallery[1]) == {"id", "caption", "width", "height", "url", "thumbnail_url"}


async def test_same_file_twice_is_a_conflict(
    client: httpx2.AsyncClient, hall: Hall, storage: MemoryStorage
) -> None:
    first = (await upload(client, jpeg())).json()

    response = await upload(client, jpeg())

    assert response.status_code == 409
    assert response.json()["error_code"] == "DUPLICATE_PICTURE"
    assert response.json()["details"] == {"existing_picture_id": first["id"]}


async def test_hall_picture_limit(
    client: httpx2.AsyncClient,
    hall: Hall,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pictures, "MAX_PICTURES_PER_HALL", 1)
    await upload(client, jpeg("red"))

    response = await upload(client, jpeg("blue"))

    assert response.status_code == 409
    assert response.json()["error_code"] == "TOO_MANY_PICTURES"


async def test_file_over_the_size_limit_is_413(
    client: httpx2.AsyncClient, hall: Hall, storage: MemoryStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pictures, "MAX_UPLOAD_BYTES", 1000)

    response = await upload(client, jpeg())

    assert response.status_code == 413
    assert response.json()["error_code"] == "PICTURE_TOO_LARGE"
    assert storage.files == {}


@pytest.mark.parametrize(
    ("data", "caption", "error_code"),
    [
        (b"not an image", None, "INVALID_PICTURE"),
        (None, "call 052-1234567", None),  # contact details in the caption
        (None, "x" * 301, None),
    ],
)
async def test_invalid_upload_is_422(
    client: httpx2.AsyncClient,
    hall: Hall,
    storage: MemoryStorage,
    data: bytes | None,
    caption: str | None,
    error_code: str | None,
) -> None:
    response = await upload(client, data or jpeg(), caption=caption)

    assert response.status_code == 422
    if error_code:
        assert response.json()["error_code"] == error_code
    assert storage.files == {}


async def test_upload_to_unknown_hall_is_404(client: httpx2.AsyncClient, hall: Hall) -> None:
    response = await client.post(
        "/api/v1/admin/venues/zqp-venue/halls/nope/pictures",
        files={"file": ("photo.jpg", jpeg(), "image/jpeg")},
        headers=AUTH,
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "HALL_NOT_FOUND"


async def test_storage_failure_saves_no_row(
    client: httpx2.AsyncClient, hall: Hall, storage: MemoryStorage, session: AsyncSession
) -> None:
    storage.fail = True

    response = await upload(client, jpeg())

    assert response.status_code == 503
    assert response.json()["error_code"] == "PICTURE_STORAGE_UNAVAILABLE"
    count = await session.scalar(
        select(func.count()).select_from(HallPicture).where(HallPicture.hall_id == hall.id)
    )
    assert count == 0


async def test_upload_without_configuration_is_503(session: AsyncSession, hall: Hall) -> None:
    async with make_client(session, storage=None) as no_storage:
        response = await upload(no_storage, jpeg())
    assert response.status_code == 503
    assert response.json()["error_code"] == "PICTURES_NOT_CONFIGURED"

    async with make_client(session, MemoryStorage(), base_url=None) as no_base_url:
        response = await upload(no_base_url, jpeg())
    assert response.status_code == 503
    assert response.json()["error_code"] == "PICTURES_NOT_CONFIGURED"


# --- public visibility --------------------------------------------------------------------------


async def test_gallery_of_unpublished_hall_is_404(
    client: httpx2.AsyncClient, hall: Hall, session: AsyncSession
) -> None:
    await upload(client, jpeg())
    hall.is_published = False
    await session.flush()

    assert (await client.get(PUBLIC)).status_code == 404
    assert len((await client.get(ADMIN, headers=AUTH)).json()) == 1


async def test_empty_gallery_needs_no_configuration(session: AsyncSession, hall: Hall) -> None:
    async with make_client(session, storage=None, base_url=None) as http:
        response = await http.get(PUBLIC)

    assert response.status_code == 200
    assert response.json() == []


# --- edit ---------------------------------------------------------------------------------------


async def test_patch_caption_and_order(client: httpx2.AsyncClient, hall: Hall) -> None:
    first = (await upload(client, jpeg("red"), caption="Old")).json()
    second = (await upload(client, jpeg("blue"))).json()

    response = await client.patch(
        f"{ADMIN}/{first['id']}", json={"caption": None, "display_order": 5}, headers=AUTH
    )

    assert response.status_code == 200
    assert response.json()["caption"] is None
    assert response.json()["display_order"] == 5
    gallery = (await client.get(PUBLIC)).json()
    assert [p["id"] for p in gallery] == [second["id"], first["id"]]


@pytest.mark.parametrize(
    "patch",
    [
        {"display_order": None},
        {"display_order": -1},
        {"caption": "mail me at someone@example.com"},
        {"storage_key": "pictures/other"},
    ],
)
async def test_invalid_picture_patch_is_422(
    client: httpx2.AsyncClient, hall: Hall, patch: dict[str, Any]
) -> None:
    picture = (await upload(client, jpeg())).json()

    response = await client.patch(f"{ADMIN}/{picture['id']}", json=patch, headers=AUTH)

    assert response.status_code == 422


async def test_picture_of_another_hall_is_404(
    client: httpx2.AsyncClient, hall: Hall, session: AsyncSession
) -> None:
    picture = (await upload(client, jpeg())).json()
    session.add(Hall(venue_id=hall.venue_id, slug="side", name="Side hall", is_published=True))
    await session.flush()

    other_hall = "/api/v1/admin/venues/zqp-venue/halls/side/pictures"
    response = await client.patch(
        f"{other_hall}/{picture['id']}", json={"caption": "x"}, headers=AUTH
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "PICTURE_NOT_FOUND"


# --- delete -------------------------------------------------------------------------------------


async def test_delete_picture_removes_row_and_files(
    client: httpx2.AsyncClient, hall: Hall, storage: MemoryStorage
) -> None:
    picture = (await upload(client, jpeg())).json()

    response = await client.delete(f"{ADMIN}/{picture['id']}", headers=AUTH)

    assert response.status_code == 204
    assert storage.files == {}
    assert (await client.get(PUBLIC)).json() == []
    again = await client.delete(f"{ADMIN}/{picture['id']}", headers=AUTH)
    assert again.status_code == 404


async def test_delete_picture_succeeds_even_if_files_cannot_be_removed(
    client: httpx2.AsyncClient, hall: Hall, storage: MemoryStorage
) -> None:
    picture = (await upload(client, jpeg())).json()
    storage.fail = True

    response = await client.delete(f"{ADMIN}/{picture['id']}", headers=AUTH)

    assert response.status_code == 204
    assert (await client.get(PUBLIC)).json() == []


@pytest.mark.parametrize(
    ("path", "confirm"),
    [("/venues/zqp-venue/halls/main", "main"), ("/venues/zqp-venue", "zqp-venue")],
)
async def test_deleting_hall_or_venue_removes_picture_files(
    client: httpx2.AsyncClient, hall: Hall, storage: MemoryStorage, path: str, confirm: str
) -> None:
    await upload(client, jpeg())
    assert storage.files

    response = await client.delete(
        f"/api/v1/admin{path}", params={"confirm": confirm}, headers=AUTH
    )

    assert response.status_code == 204
    assert storage.files == {}
