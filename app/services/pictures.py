"""
Hall pictures: the gallery query (public and admin) and admin upload / edit / delete.

Rows live in `hall_pictures`; files live in picture storage (Vercel Blob). On upload the files are
written before the row, on delete the row is removed before the files: a failure in between
can leave an unused file in the bucket, never a row pointing to a missing file.
"""

from typing import Any

import anyio
from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    DuplicatePictureError,
    PictureNotFoundError,
    PicturesNotConfiguredError,
    PictureTooLargeError,
    TooManyPicturesError,
)
from app.db.models import Hall, HallPicture, Venue
from app.schemas.pictures import Picture, PicturePatch
from app.services.picture_processing import file_key, file_keys, process_picture
from app.services.picture_storage import PictureStorage, public_base_url
from app.services.venues import find_hall

MAX_PICTURES_PER_HALL = 20
# Vercel Functions accept request bodies up to 4.5 MB (multipart overhead included)
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
_MAX_DISPLAY_ORDER = 32767


def get_pictures_base_url(request: Request) -> str | None:
    """Route dependency: public base URL of picture files, without a trailing slash."""
    return public_base_url(request.app.state.settings)


def require_base_url(base_url: str | None) -> str:
    if base_url is None:
        raise PicturesNotConfiguredError("BLOB_READ_WRITE_TOKEN or PICTURES_BASE_URL")
    return base_url


def to_model[P: Picture](picture: HallPicture, base_url: str | None, model: type[P]) -> P:
    base = require_base_url(base_url)
    values: dict[str, Any] = {
        "id": picture.id,
        "caption": picture.caption,
        "width": picture.width,
        "height": picture.height,
        "url": f"{base}/{file_key(picture.storage_key, 'large')}",
        "thumbnail_url": f"{base}/{file_key(picture.storage_key, 'thumb')}",
        "display_order": picture.display_order,  # admin fields: ignored by the public model
        "storage_key": picture.storage_key,
        "created_at": picture.created_at,
    }
    return model.model_validate(values)


async def list_pictures[P: Picture](
    session: AsyncSession,
    venue_slug: str,
    hall_slug: str,
    *,
    base_url: str | None,
    published_only: bool = True,
    model: type[P] = Picture,  # type: ignore[assignment]
) -> list[P]:
    hall = await find_hall(session, venue_slug, hall_slug, published_only=published_only)
    rows = await session.scalars(
        select(HallPicture)
        .where(HallPicture.hall_id == hall.id)
        .order_by(HallPicture.display_order, HallPicture.id)
    )
    return [to_model(picture, base_url, model) for picture in rows]


async def add_picture(
    session: AsyncSession,
    storage: PictureStorage,
    venue_slug: str,
    hall_slug: str,
    data: bytes,
    caption: str | None,
) -> HallPicture:
    if len(data) > MAX_UPLOAD_BYTES:
        raise PictureTooLargeError(MAX_UPLOAD_BYTES)
    hall = await find_hall(session, venue_slug, hall_slug, published_only=False)
    count = await session.scalar(
        select(func.count()).select_from(HallPicture).where(HallPicture.hall_id == hall.id)
    )
    if (count or 0) >= MAX_PICTURES_PER_HALL:
        raise TooManyPicturesError(MAX_PICTURES_PER_HALL)

    processed = await anyio.to_thread.run_sync(process_picture, data)
    storage_key = f"pictures/{processed.content_hash}"
    existing = await session.scalar(
        select(HallPicture.id).where(HallPicture.storage_key == storage_key)
    )
    if existing is not None:
        raise DuplicatePictureError(existing)

    for size, body in processed.files.items():
        await storage.put(file_key(storage_key, size), body, "image/webp")

    last_order = await session.scalar(
        select(func.max(HallPicture.display_order)).where(HallPicture.hall_id == hall.id)
    )
    picture = HallPicture(
        hall_id=hall.id,
        storage_key=storage_key,
        caption=caption,
        width=processed.width,
        height=processed.height,
        display_order=0 if last_order is None else min(last_order + 1, _MAX_DISPLAY_ORDER),
    )
    session.add(picture)
    await session.flush()
    await session.refresh(picture)  # server-side created_at
    return picture


async def find_picture(
    session: AsyncSession, venue_slug: str, hall_slug: str, picture_id: int
) -> HallPicture:
    hall = await find_hall(session, venue_slug, hall_slug, published_only=False)
    picture = await session.scalar(
        select(HallPicture).where(HallPicture.id == picture_id, HallPicture.hall_id == hall.id)
    )
    if picture is None:
        raise PictureNotFoundError(picture_id)
    return picture


async def patch_picture(
    session: AsyncSession, venue_slug: str, hall_slug: str, picture_id: int, patch: PicturePatch
) -> HallPicture:
    picture = await find_picture(session, venue_slug, hall_slug, picture_id)
    for field, value in patch.model_dump(exclude_unset=True).items():
        setattr(picture, field, value)
    await session.flush()
    return picture


async def delete_picture(
    session: AsyncSession, venue_slug: str, hall_slug: str, picture_id: int
) -> list[str]:
    """Deletes the row; returns its file keys to delete from storage after the commit."""
    picture = await find_picture(session, venue_slug, hall_slug, picture_id)
    await session.delete(picture)
    await session.flush()
    return file_keys(picture.storage_key)


async def file_keys_of(
    session: AsyncSession, venue_slug: str, hall_slug: str | None = None
) -> list[str]:
    """File keys of every picture of a venue (or one hall), read before deleting it."""
    query = (
        select(HallPicture.storage_key)
        .join(Hall, Hall.id == HallPicture.hall_id)
        .join(Venue, Venue.id == Hall.venue_id)
        .where(Venue.slug == venue_slug)
    )
    if hall_slug is not None:
        query = query.where(Hall.slug == hall_slug)
    return [key for storage_key in await session.scalars(query) for key in file_keys(storage_key)]
