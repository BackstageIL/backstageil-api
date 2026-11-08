"""Vendors directory API (BSIL-79) against a real database: public list and page, admin edits,
logo and photos, and the vendors part of the site snapshot.

Files go to an in-memory storage; rows are rolled back after each test. Test vendors have unique
slugs ("zqv-..."), so the tests also pass on a database that has real vendors.
"""

from collections.abc import AsyncIterator, Sequence
from io import BytesIO
from typing import Any

import httpx2
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import PUBLIC_CACHE_CONTROL
from app.core.config import Settings
from app.core.security import hash_api_key
from app.db.dependencies import get_session
from app.db.models import Vendor, VendorPicture
from app.main import create_app
from app.services.picture_storage import get_optional_picture_storage, get_picture_storage
from app.services.vendors import MAX_PHOTOS_PER_VENDOR

pytestmark = pytest.mark.anyio

KEY = "integration-test-admin-key-0123456789"
AUTH = {"X-API-Key": KEY}
BASE_URL = "https://pictures.example.test"
PUBLIC = "/api/v1/vendors"
ADMIN = "/api/v1/admin/vendors"
SLUG = "zqv-fx"


class MemoryStorage:
    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.files[key] = (data, content_type)

    async def delete(self, keys: Sequence[str]) -> None:
        for key in keys:
            self.files.pop(key, None)


@pytest.fixture
def storage() -> MemoryStorage:
    return MemoryStorage()


@pytest.fixture
async def client(
    session: AsyncSession, storage: MemoryStorage
) -> AsyncIterator[httpx2.AsyncClient]:
    settings = Settings(
        _env_file=None,
        environment="ci",
        database_url=None,
        admin_api_key_hash=hash_api_key(KEY),
        pictures_base_url=BASE_URL,
    )
    app = create_app(settings)

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_picture_storage] = lambda: storage
    app.dependency_overrides[get_optional_picture_storage] = lambda: storage
    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def vendor_body(**changes: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "slug": SLUG,
        "name": "Zqv FX",
        "name_he": "זקו אפקט",
        "description": "Smoke jets and DJ booths.",
        "description_he": "עשן ואפקט לבמה.",
        "categories": ["dj_effects"],
        "districts": [],
        "phone": "+972 54-000-0000",
        "email": "info@zqv.example",
    }
    return body | changes


async def create(client: httpx2.AsyncClient, **changes: Any) -> httpx2.Response:
    return await client.post(ADMIN, json=vendor_body(**changes), headers=AUTH)


async def publish(client: httpx2.AsyncClient, slug: str = SLUG) -> None:
    response = await client.post(f"{ADMIN}/{slug}/publish", headers=AUTH)
    assert response.status_code == 200


def jpeg(color: str = "red", size: tuple[int, int] = (800, 400)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, "JPEG")
    return buffer.getvalue()


async def upload(
    client: httpx2.AsyncClient, data: bytes, *, is_logo: bool = False, slug: str = SLUG
) -> httpx2.Response:
    return await client.post(
        f"{ADMIN}/{slug}/pictures",
        files={"file": ("photo.jpg", data, "image/jpeg")},
        data={"is_logo": str(is_logo).lower()},
        headers=AUTH,
    )


def ours(vendors: list[dict[str, Any]]) -> list[str]:
    return [v["slug"] for v in vendors if v["slug"].startswith("zqv-")]


# --- auth ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", ""),
        ("POST", ""),
        ("GET", f"/{SLUG}"),
        ("PATCH", f"/{SLUG}"),
        ("DELETE", f"/{SLUG}"),
        ("POST", f"/{SLUG}/publish"),
        ("POST", f"/{SLUG}/pictures"),
        ("DELETE", f"/{SLUG}/pictures/1"),
    ],
)
async def test_admin_vendor_routes_require_the_key(
    client: httpx2.AsyncClient, method: str, path: str
) -> None:
    response = await client.request(method, f"{ADMIN}{path}")

    assert response.status_code == 401


# --- create, publish, public view ---------------------------------------------------------------


async def test_a_new_vendor_is_unpublished_until_published(client: httpx2.AsyncClient) -> None:
    created = await create(client)
    assert created.status_code == 201
    assert created.json()["is_published"] is False
    assert (await client.get(f"{PUBLIC}/{SLUG}")).status_code == 404
    assert SLUG not in ours((await client.get(PUBLIC)).json())

    await publish(client)

    page = await client.get(f"{PUBLIC}/{SLUG}")
    assert page.status_code == 200
    assert page.headers["cache-control"] == PUBLIC_CACHE_CONTROL
    assert page.json() == {
        "slug": SLUG,
        "name": "Zqv FX",
        "name_he": "זקו אפקט",
        "description": "Smoke jets and DJ booths.",
        "description_he": "עשן ואפקט לבמה.",
        "categories": ["dj_effects"],
        "districts": [],
        "phone": "+972 54-000-0000",
        "email": "info@zqv.example",
        "logo": None,
        "pictures": [],
    }
    assert SLUG in ours((await client.get(PUBLIC)).json())


async def test_unpublish_hides_the_vendor(client: httpx2.AsyncClient) -> None:
    await create(client)
    await publish(client)

    response = await client.post(f"{ADMIN}/{SLUG}/unpublish", headers=AUTH)

    assert response.json() == {"slug": SLUG, "is_published": False}
    assert (await client.get(f"{PUBLIC}/{SLUG}")).status_code == 404


async def test_public_list_is_in_display_order_then_by_name(client: httpx2.AsyncClient) -> None:
    for slug, name, order in (
        ("zqv-b", "Zqv Beta", 0),
        ("zqv-a", "zqv alpha", 0),
        ("zqv-c", "Zqv Gamma", 1),
    ):
        await create(client, slug=slug, name=name, display_order=order)
        await publish(client, slug)

    assert ours((await client.get(PUBLIC)).json()) == ["zqv-a", "zqv-b", "zqv-c"]


async def test_unknown_vendor_is_404(client: httpx2.AsyncClient) -> None:
    response = await client.get(f"{PUBLIC}/zqv-nobody")

    assert response.status_code == 404
    assert response.json()["error_code"] == "VENDOR_NOT_FOUND"


async def test_a_slug_can_be_used_once(client: httpx2.AsyncClient) -> None:
    await create(client)

    response = await create(client, name="Another")

    assert response.status_code == 409


# --- validation ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"description": "Call us at 054-1234567"},
        {"description_he": "כתבו ל-info@zqv.example"},
        {"name": "Zqv 054-1234567"},
        {"phone": "call me"},
        {"email": "not-an-email"},
        {"categories": []},
        {"categories": ["catering"]},
        {"districts": ["mars"]},
        {"slug": "Not A Slug"},
        {"is_published": True},
    ],
)
async def test_invalid_vendor_is_refused(
    client: httpx2.AsyncClient, changes: dict[str, Any]
) -> None:
    response = await create(client, **changes)

    assert response.status_code == 422


async def test_the_database_refuses_unknown_categories_and_districts(
    session: AsyncSession,
) -> None:
    invalid: list[dict[str, Any]] = [
        {"categories": ["catering"]},
        {"categories": []},
        {"districts": ["mars"]},
    ]
    for values in invalid:
        fields: dict[str, Any] = {"slug": "zqv-db", "name": "Zqv DB", "categories": ["sound"]}
        async with session.begin_nested():
            session.add(Vendor(**(fields | values)))
            with pytest.raises(IntegrityError):
                await session.flush()


# --- edit, delete -------------------------------------------------------------------------------


async def test_patch_changes_only_the_fields_sent(client: httpx2.AsyncClient) -> None:
    await create(client)

    response = await client.patch(
        f"{ADMIN}/{SLUG}",
        json={"districts": ["north", "haifa"], "email": None, "categories": ["sound", "lighting"]},
        headers=AUTH,
    )

    body = response.json()
    assert response.status_code == 200
    assert body["districts"] == ["north", "haifa"]
    assert body["categories"] == ["sound", "lighting"]
    assert body["email"] is None
    assert body["phone"] == "+972 54-000-0000"


@pytest.mark.parametrize("field", ["name", "categories", "districts", "display_order"])
async def test_patch_cannot_clear_required_fields(client: httpx2.AsyncClient, field: str) -> None:
    await create(client)

    response = await client.patch(f"{ADMIN}/{SLUG}", json={field: None}, headers=AUTH)

    assert response.status_code == 422


async def test_delete_needs_the_slug_repeated_and_removes_the_files(
    client: httpx2.AsyncClient, session: AsyncSession, storage: MemoryStorage
) -> None:
    await create(client)
    await upload(client, jpeg(), is_logo=True)
    assert storage.files

    refused = await client.delete(f"{ADMIN}/{SLUG}", params={"confirm": "wrong"}, headers=AUTH)
    deleted = await client.delete(f"{ADMIN}/{SLUG}", params={"confirm": SLUG}, headers=AUTH)

    assert refused.status_code == 422
    assert deleted.status_code == 204
    assert storage.files == {}
    assert await session.scalar(select(Vendor).where(Vendor.slug == SLUG)) is None


# --- logo and photos ----------------------------------------------------------------------------


async def test_logo_and_photos_are_shown_apart(
    client: httpx2.AsyncClient, storage: MemoryStorage
) -> None:
    await create(client)
    logo = await upload(client, jpeg("black"), is_logo=True)
    photo = await upload(client, jpeg("blue"))
    await publish(client)

    page = (await client.get(f"{PUBLIC}/{SLUG}")).json()

    assert logo.status_code == 201
    assert photo.status_code == 201
    assert page["logo"]["id"] == logo.json()["id"]
    assert page["logo"]["url"].startswith(f"{BASE_URL}/vendor-pictures/")
    assert [p["id"] for p in page["pictures"]] == [photo.json()["id"]]
    assert all(key.startswith("vendor-pictures/") for key in storage.files)
    assert {content_type for _, content_type in storage.files.values()} == {"image/webp"}


async def test_a_vendor_has_one_logo(client: httpx2.AsyncClient) -> None:
    await create(client)
    first = await upload(client, jpeg("black"), is_logo=True)

    second = await upload(client, jpeg("white"), is_logo=True)

    assert second.status_code == 409
    assert second.json()["error_code"] == "VENDOR_LOGO_EXISTS"
    assert second.json()["details"] == {"existing_picture_id": first.json()["id"]}


async def test_photos_are_limited(client: httpx2.AsyncClient, session: AsyncSession) -> None:
    await create(client)
    vendor = await session.scalar(select(Vendor).where(Vendor.slug == SLUG))
    assert vendor is not None
    session.add_all(
        VendorPicture(vendor_id=vendor.id, storage_key=f"vendor-pictures/zqv{i}", width=1, height=1)
        for i in range(MAX_PHOTOS_PER_VENDOR)
    )
    await session.flush()

    too_many = await upload(client, jpeg("green"))
    logo = await upload(client, jpeg("black"), is_logo=True)

    assert too_many.status_code == 409
    assert too_many.json()["error_code"] == "TOO_MANY_PICTURES"
    assert logo.status_code == 201  # the logo doesn't count


async def test_picture_caption_and_order_can_change_and_a_picture_can_go(
    client: httpx2.AsyncClient, storage: MemoryStorage
) -> None:
    await create(client)
    first = (await upload(client, jpeg("red"))).json()
    second = (await upload(client, jpeg("blue"))).json()

    patched = await client.patch(
        f"{ADMIN}/{SLUG}/pictures/{second['id']}",
        json={"caption": "DJ booth", "display_order": 0},
        headers=AUTH,
    )
    await client.patch(
        f"{ADMIN}/{SLUG}/pictures/{first['id']}", json={"display_order": 5}, headers=AUTH
    )
    admin = (await client.get(f"{ADMIN}/{SLUG}", headers=AUTH)).json()
    deleted = await client.delete(f"{ADMIN}/{SLUG}/pictures/{first['id']}", headers=AUTH)
    missing = await client.delete(f"{ADMIN}/{SLUG}/pictures/{first['id']}", headers=AUTH)

    assert patched.json()["caption"] == "DJ booth"
    assert [p["id"] for p in admin["pictures"]] == [second["id"], first["id"]]
    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert all(first["storage_key"] not in key for key in storage.files)


# --- admin list and site snapshot ---------------------------------------------------------------


async def test_admin_list_includes_unpublished_vendors(client: httpx2.AsyncClient) -> None:
    await create(client)

    response = await client.get(ADMIN, headers=AUTH)

    assert SLUG in ours(response.json())


async def test_snapshot_vendors_equal_the_public_list(client: httpx2.AsyncClient) -> None:
    await create(client)
    await create(client, slug="zqv-hidden", name="Zqv Hidden")
    await upload(client, jpeg("black"), is_logo=True)
    await publish(client)

    snapshot = (await client.get("/api/v1/site/snapshot")).json()
    public = (await client.get(PUBLIC)).json()

    assert snapshot["vendors"] == public
    assert ours(snapshot["vendors"]) == [SLUG]
