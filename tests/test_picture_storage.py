"""R2 picture storage (with botocore's Stubber: no network) and its route dependencies."""

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from botocore.stub import Stubber

from app.core.config import Settings
from app.core.exceptions import PicturesNotConfiguredError, PictureStorageUnavailableError
from app.services.picture_storage import (
    IMMUTABLE_CACHE_CONTROL,
    R2Storage,
    delete_files_quietly,
    get_optional_picture_storage,
    get_picture_storage,
    storage_from_settings,
)

pytestmark = pytest.mark.anyio

R2: dict[str, Any] = {
    "r2_account_id": "0123456789abcdef",
    "r2_access_key_id": "test-access-key",
    "r2_secret_access_key": "test-secret-key",
    "r2_bucket": "test-bucket",
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def storage() -> R2Storage:
    return R2Storage("0123456789abcdef", "test-access-key", "test-secret-key", "test-bucket")


@pytest.fixture
def stub(storage: R2Storage) -> Iterator[Stubber]:
    with Stubber(storage._client) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()


def request_for(settings: Settings) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings, picture_storage=None))
    )


def test_client_points_at_the_account_endpoint(storage: R2Storage) -> None:
    assert storage._client.meta.endpoint_url == "https://0123456789abcdef.r2.cloudflarestorage.com"


async def test_put_stores_an_immutable_file(storage: R2Storage, stub: Stubber) -> None:
    stub.add_response(
        "put_object",
        {},
        {
            "Bucket": "test-bucket",
            "Key": "pictures/abc/large.webp",
            "Body": b"webp-bytes",
            "ContentType": "image/webp",
            "CacheControl": IMMUTABLE_CACHE_CONTROL,
        },
    )

    await storage.put("pictures/abc/large.webp", b"webp-bytes", "image/webp")


async def test_delete_removes_all_keys_in_one_request(storage: R2Storage, stub: Stubber) -> None:
    keys = ["pictures/abc/large.webp", "pictures/abc/thumb.webp"]
    stub.add_response(
        "delete_objects",
        {},
        {
            "Bucket": "test-bucket",
            "Delete": {"Objects": [{"Key": key} for key in keys], "Quiet": True},
        },
    )

    await storage.delete(keys)
    await storage.delete([])  # nothing to delete: no request


async def test_storage_errors_become_unavailable(storage: R2Storage, stub: Stubber) -> None:
    stub.add_client_error("put_object", service_error_code="InternalError", http_status_code=500)

    with pytest.raises(PictureStorageUnavailableError):
        await storage.put("pictures/abc/large.webp", b"x", "image/webp")


async def test_delete_quietly_swallows_storage_errors(storage: R2Storage, stub: Stubber) -> None:
    stub.add_client_error("delete_objects", service_error_code="InternalError")

    await delete_files_quietly(storage, ["pictures/abc/large.webp"])
    await delete_files_quietly(None, ["pictures/abc/large.webp"])  # not configured: logged only
    await delete_files_quietly(storage, [])


def test_storage_needs_all_four_settings() -> None:
    assert storage_from_settings(Settings(_env_file=None)) is None
    partial = {**R2, "r2_secret_access_key": ""}
    assert storage_from_settings(Settings(_env_file=None, **partial)) is None
    assert isinstance(storage_from_settings(Settings(_env_file=None, **R2)), R2Storage)


def test_dependencies_create_the_storage_once() -> None:
    request = request_for(Settings(_env_file=None, **R2))

    first = get_picture_storage(request)

    assert isinstance(first, R2Storage)
    assert get_optional_picture_storage(request) is first


def test_writing_routes_answer_503_without_r2() -> None:
    request = request_for(Settings(_env_file=None))

    assert get_optional_picture_storage(request) is None
    with pytest.raises(PicturesNotConfiguredError):
        get_picture_storage(request)
