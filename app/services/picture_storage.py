"""
Object storage for picture files, behind a small interface so the provider can be swapped.

Production uses Cloudflare R2 through its S3-compatible API. Files are immutable (their keys
contain a content hash), so they are stored with a one-year cache lifetime.
"""

from collections.abc import Callable, Sequence
from functools import partial
from typing import TYPE_CHECKING, Protocol

import anyio
from fastapi import Request

from app.core.config import Settings
from app.core.exceptions import PicturesNotConfiguredError, PictureStorageUnavailableError
from app.core.logger import get_logger

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client

logger = get_logger(__name__)

IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"


class PictureStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def delete(self, keys: Sequence[str]) -> None: ...


class R2Storage:
    """Cloudflare R2 bucket. boto3 is synchronous, so calls run in a worker thread."""

    def __init__(
        self, account_id: str, access_key_id: str, secret_access_key: str, bucket: str
    ) -> None:
        # Imported here: boto3 is slow to import and only admin picture routes need it.
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self._client: S3Client = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            config=Config(
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
                # R2 doesn't support every checksum algorithm newer boto3 adds by default
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await self._call(
            partial(
                self._client.put_object,
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                CacheControl=IMMUTABLE_CACHE_CONTROL,
            )
        )

    async def delete(self, keys: Sequence[str]) -> None:
        if not keys:
            return
        await self._call(
            partial(
                self._client.delete_objects,
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
            )
        )

    async def _call(self, operation: Callable[[], object]) -> None:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            await anyio.to_thread.run_sync(operation)
        except (BotoCoreError, ClientError) as exc:
            logger.error("Picture storage error: %s", exc)
            raise PictureStorageUnavailableError() from exc


def storage_from_settings(settings: Settings) -> PictureStorage | None:
    if not settings.r2_configured:
        return None
    assert settings.r2_account_id and settings.r2_access_key_id and settings.r2_bucket
    assert settings.r2_secret_access_key is not None
    return R2Storage(
        settings.r2_account_id,
        settings.r2_access_key_id,
        settings.r2_secret_access_key.get_secret_value(),
        settings.r2_bucket,
    )


def get_optional_picture_storage(request: Request) -> PictureStorage | None:
    """Route dependency: the configured storage, created on first use, or None."""
    state = request.app.state
    if state.picture_storage is None:
        state.picture_storage = storage_from_settings(state.settings)
    storage: PictureStorage | None = state.picture_storage
    return storage


def get_picture_storage(request: Request) -> PictureStorage:
    """Route dependency for routes that write files: 503 when R2 is not configured."""
    storage = get_optional_picture_storage(request)
    if storage is None:
        raise PicturesNotConfiguredError("R2_* bucket settings")
    return storage


async def delete_files_quietly(storage: PictureStorage | None, keys: Sequence[str]) -> None:
    """Best effort, after the rows are already deleted: a leftover file only costs storage."""
    if not keys:
        return
    if storage is None:
        logger.warning("Picture storage not configured; %d files left in the bucket", len(keys))
        return
    try:
        await storage.delete(keys)
    except PictureStorageUnavailableError:
        logger.warning("Could not delete %d picture files; they stay in the bucket", len(keys))
