"""
Object storage for picture files, behind a small interface so the provider can be swapped.

Production uses a public Vercel Blob store, called through its HTTP API (two calls: upload and
delete; the official SDK is avoided for its many dependencies and telemetry). Files are immutable
(their keys contain a content hash), so they are stored with a one-year cache lifetime.
"""

from collections.abc import Sequence
from typing import Any, Protocol

import httpx2
from fastapi import Request

from app.core.config import Settings
from app.core.exceptions import PicturesNotConfiguredError, PictureStorageUnavailableError
from app.core.logger import get_logger

logger = get_logger(__name__)

BLOB_API_URL = "https://vercel.com/api/blob"
BLOB_API_VERSION = "11"
CACHE_MAX_AGE_SECONDS = 365 * 24 * 3600
_TOKEN_SETTING = "a valid BLOB_READ_WRITE_TOKEN"


class PictureStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def delete(self, keys: Sequence[str]) -> None: ...


def blob_store_url(token: str) -> str:
    """Public URL of the store a read-write token belongs to.

    Tokens look like `vercel_blob_rw_<storeId>_<secret>`; files are served from
    `https://<storeId>.public.blob.vercel-storage.com/<pathname>`.
    """
    parts = token.split("_")
    if len(parts) < 5 or parts[:3] != ["vercel", "blob", "rw"] or not parts[3].isalnum():
        raise PicturesNotConfiguredError(_TOKEN_SETTING)
    return f"https://{parts[3].lower()}.public.blob.vercel-storage.com"


class VercelBlobStorage:
    """A public Vercel Blob store. `transport` is for tests."""

    def __init__(self, token: str, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self.base_url = blob_store_url(token)
        self._token = token
        self._transport = transport

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await self._send(
            "PUT",
            BLOB_API_URL,
            params={"pathname": key},
            content=data,
            headers={
                "x-vercel-blob-access": "public",
                "x-content-type": content_type,
                "x-add-random-suffix": "0",
                # Same key = same content hash: rewriting a file left by a failed upload is safe
                "x-allow-overwrite": "1",
                "x-cache-control-max-age": str(CACHE_MAX_AGE_SECONDS),
            },
        )

    async def delete(self, keys: Sequence[str]) -> None:
        if not keys:
            return
        urls = [f"{self.base_url}/{key}" for key in keys]
        await self._send("POST", f"{BLOB_API_URL}/delete", json={"urls": urls})

    async def _send(self, method: str, url: str, **kwargs: Any) -> None:
        # Retries cover connection failures only; a request is never sent twice.
        transport = self._transport or httpx2.AsyncHTTPTransport(retries=2)
        headers = {"authorization": f"Bearer {self._token}", "x-api-version": BLOB_API_VERSION}
        try:
            async with httpx2.AsyncClient(
                transport=transport, headers=headers, timeout=30
            ) as client:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            # The body explains the error (e.g. invalid token); it never contains the token.
            logger.error(
                "Picture storage answered %s: %s", exc.response.status_code, exc.response.text[:300]
            )
            raise PictureStorageUnavailableError() from exc
        except httpx2.HTTPError as exc:
            logger.error("Picture storage request failed: %s", exc.__class__.__name__)
            raise PictureStorageUnavailableError() from exc


def storage_from_settings(settings: Settings) -> PictureStorage | None:
    if settings.blob_read_write_token is None:
        return None
    return VercelBlobStorage(settings.blob_read_write_token.get_secret_value())


def public_base_url(settings: Settings) -> str | None:
    """Base URL of picture files: PICTURES_BASE_URL if set, else the Blob store's own URL."""
    if settings.pictures_base_url is not None:
        return str(settings.pictures_base_url).rstrip("/")
    if settings.blob_read_write_token is None:
        return None
    try:
        return blob_store_url(settings.blob_read_write_token.get_secret_value())
    except PicturesNotConfiguredError:
        return None


def get_optional_picture_storage(request: Request) -> PictureStorage | None:
    """Route dependency: the configured storage, created on first use, or None."""
    state = request.app.state
    if state.picture_storage is None:
        try:
            state.picture_storage = storage_from_settings(state.settings)
        except PicturesNotConfiguredError:
            logger.warning("BLOB_READ_WRITE_TOKEN is not a Vercel Blob read-write token")
    storage: PictureStorage | None = state.picture_storage
    return storage


def get_picture_storage(request: Request) -> PictureStorage:
    """Route dependency for routes that write files: 503 when storage is not configured."""
    storage = get_optional_picture_storage(request)
    if storage is None:
        raise PicturesNotConfiguredError(_TOKEN_SETTING)
    return storage


async def delete_files_quietly(storage: PictureStorage | None, keys: Sequence[str]) -> None:
    """Best effort, after the rows are already deleted: a leftover file only costs storage."""
    if not keys:
        return
    if storage is None:
        logger.warning("Picture storage not configured; %d files left in the store", len(keys))
        return
    try:
        await storage.delete(keys)
    except PictureStorageUnavailableError:
        logger.warning("Could not delete %d picture files; they stay in the store", len(keys))
