"""Vercel Blob picture storage (HTTP calls checked with a mock transport: no network)."""

import json
from types import SimpleNamespace
from typing import Any

import httpx2
import pytest

from app.core.config import Settings
from app.core.exceptions import PicturesNotConfiguredError, PictureStorageUnavailableError
from app.services.picture_storage import (
    BLOB_API_URL,
    CACHE_MAX_AGE_SECONDS,
    VercelBlobStorage,
    blob_store_url,
    delete_files_quietly,
    get_optional_picture_storage,
    get_picture_storage,
    public_base_url,
    storage_from_settings,
)

pytestmark = pytest.mark.anyio

TOKEN = "vercel_blob_rw_AbC123xyz_s3cretPart_with_underscores"
STORE_URL = "https://abc123xyz.public.blob.vercel-storage.com"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Recorder:
    """Mock transport handler: records requests and answers with a fixed status."""

    def __init__(self, status: int = 200, body: dict[str, Any] | None = None) -> None:
        self.status = status
        self.body = body or {}
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(self.status, json=self.body)


def storage_with(recorder: Recorder) -> VercelBlobStorage:
    return VercelBlobStorage(TOKEN, transport=httpx2.MockTransport(recorder))


def request_for(settings: Settings) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings, picture_storage=None))
    )


def test_store_url_comes_from_the_token() -> None:
    assert blob_store_url(TOKEN) == STORE_URL


@pytest.mark.parametrize(
    "token", ["", "not-a-token", "vercel_blob_rw_", "vercel_blob_ro_abc_secret", "a_b_c_d_e"]
)
def test_malformed_token_is_not_configured(token: str) -> None:
    with pytest.raises(PicturesNotConfiguredError):
        blob_store_url(token)


async def test_put_uploads_a_public_immutable_file() -> None:
    recorder = Recorder(body={"url": f"{STORE_URL}/pictures/abc/large.webp"})

    await storage_with(recorder).put("pictures/abc/large.webp", b"webp-bytes", "image/webp")

    (request,) = recorder.requests
    assert request.method == "PUT"
    assert str(request.url) == f"{BLOB_API_URL}?pathname=pictures%2Fabc%2Flarge.webp"
    assert request.content == b"webp-bytes"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["x-api-version"] == "11"
    assert request.headers["x-vercel-blob-access"] == "public"
    assert request.headers["x-content-type"] == "image/webp"
    assert request.headers["x-add-random-suffix"] == "0"
    assert request.headers["x-cache-control-max-age"] == str(CACHE_MAX_AGE_SECONDS)


async def test_delete_sends_all_urls_in_one_request() -> None:
    recorder = Recorder()
    keys = ["pictures/abc/large.webp", "pictures/abc/thumb.webp"]

    await storage_with(recorder).delete(keys)
    await storage_with(recorder).delete([])  # nothing to delete: no request

    (request,) = recorder.requests
    assert (request.method, str(request.url)) == ("POST", f"{BLOB_API_URL}/delete")
    assert json.loads(request.content) == {"urls": [f"{STORE_URL}/{key}" for key in keys]}


@pytest.mark.parametrize("status", [400, 403, 500, 503])
async def test_error_answers_become_unavailable(status: int) -> None:
    recorder = Recorder(status, {"error": {"code": "forbidden", "message": "Invalid token"}})

    with pytest.raises(PictureStorageUnavailableError):
        await storage_with(recorder).put("pictures/abc/large.webp", b"x", "image/webp")


async def test_network_failure_becomes_unavailable() -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    storage = VercelBlobStorage(TOKEN, transport=httpx2.MockTransport(fail))

    with pytest.raises(PictureStorageUnavailableError):
        await storage.delete(["pictures/abc/large.webp"])


async def test_delete_quietly_swallows_storage_errors() -> None:
    storage = storage_with(Recorder(500))

    await delete_files_quietly(storage, ["pictures/abc/large.webp"])
    await delete_files_quietly(None, ["pictures/abc/large.webp"])  # not configured: logged only
    await delete_files_quietly(storage, [])


def test_storage_and_base_url_from_settings() -> None:
    assert storage_from_settings(Settings(_env_file=None)) is None
    assert public_base_url(Settings(_env_file=None)) is None

    settings = Settings(_env_file=None, blob_read_write_token=TOKEN)
    assert isinstance(storage_from_settings(settings), VercelBlobStorage)
    assert public_base_url(settings) == STORE_URL

    custom = Settings(
        _env_file=None, blob_read_write_token=TOKEN, pictures_base_url="https://img.example.com"
    )
    assert public_base_url(custom) == "https://img.example.com"
    assert public_base_url(Settings(_env_file=None, blob_read_write_token="bad")) is None


def test_dependencies_create_the_storage_once() -> None:
    request = request_for(Settings(_env_file=None, blob_read_write_token=TOKEN))

    first = get_picture_storage(request)

    assert isinstance(first, VercelBlobStorage)
    assert get_optional_picture_storage(request) is first


@pytest.mark.parametrize("token", [None, "malformed"])
def test_writing_routes_answer_503_without_a_valid_token(token: str | None) -> None:
    request = request_for(Settings(_env_file=None, blob_read_write_token=token))

    assert get_optional_picture_storage(request) is None
    with pytest.raises(PicturesNotConfiguredError):
        get_picture_storage(request)
