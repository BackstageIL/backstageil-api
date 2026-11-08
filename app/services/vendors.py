"""
Vendors directory (BSIL-79): public list and page, admin edits, logo and photos.

A vendor is never tied to a venue. Pictures go through the same processing as hall pictures
(WebP, no metadata) under their own prefix `vendor-pictures/`; at most one is the logo.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConfirmationMismatchError,
    PictureNotFoundError,
    PictureTooLargeError,
    TooManyPicturesError,
    VendorLogoExistsError,
    VendorNotFoundError,
)
from app.db.models import Vendor, VendorPicture
from app.schemas.pictures import AdminPicture, Picture, PicturePatch
from app.schemas.vendors import AdminVendor, VendorCreate, VendorPatch
from app.schemas.vendors import Vendor as PublicVendor
from app.services.picture_processing import file_keys
from app.services.picture_storage import PictureStorage
from app.services.pictures import MAX_UPLOAD_BYTES, process_and_store, to_model

MAX_PHOTOS_PER_VENDOR = 8  # besides the logo
_MAX_DISPLAY_ORDER = 32767
_PUBLIC_ORDER = (Vendor.display_order, func.lower(Vendor.name), Vendor.id)
_PICTURE_ORDER = (VendorPicture.display_order, VendorPicture.id)


async def _pictures_by_vendor(
    session: AsyncSession, vendor_ids: Iterable[int]
) -> defaultdict[int, list[VendorPicture]]:
    groups: defaultdict[int, list[VendorPicture]] = defaultdict(list)
    ids = list(vendor_ids)
    if ids:
        rows = await session.scalars(
            select(VendorPicture).where(VendorPicture.vendor_id.in_(ids)).order_by(*_PICTURE_ORDER)
        )
        for row in rows:
            groups[row.vendor_id].append(row)
    return groups


def _fields(vendor: Vendor) -> dict[str, Any]:
    return {
        "slug": vendor.slug,
        "name": vendor.name,
        "name_he": vendor.name_he,
        "description": vendor.description,
        "description_he": vendor.description_he,
        "categories": vendor.categories,
        "districts": vendor.districts,
        "phone": vendor.phone,
        "email": vendor.email,
    }


def public_view(
    vendor: Vendor, pictures: Sequence[VendorPicture], base_url: str | None
) -> PublicVendor:
    logo = next((p for p in pictures if p.is_logo), None)
    return PublicVendor(
        **_fields(vendor),
        logo=to_model(logo, base_url, Picture) if logo else None,
        pictures=[to_model(p, base_url, Picture) for p in pictures if not p.is_logo],
    )


def admin_view(
    vendor: Vendor, pictures: Sequence[VendorPicture], base_url: str | None
) -> AdminVendor:
    logo = next((p for p in pictures if p.is_logo), None)
    return AdminVendor(
        **_fields(vendor),
        is_published=vendor.is_published,
        display_order=vendor.display_order,
        logo=to_model(logo, base_url, AdminPicture) if logo else None,
        pictures=[to_model(p, base_url, AdminPicture) for p in pictures if not p.is_logo],
        created_at=vendor.created_at,
        updated_at=vendor.updated_at,
    )


async def published_vendors(session: AsyncSession, *, base_url: str | None) -> list[PublicVendor]:
    """Every published vendor, by display order then name (2 queries, whatever the count)."""
    vendors = list(
        await session.scalars(select(Vendor).where(Vendor.is_published).order_by(*_PUBLIC_ORDER))
    )
    pictures = await _pictures_by_vendor(session, (v.id for v in vendors))
    return [public_view(v, pictures[v.id], base_url) for v in vendors]


async def find_vendor(session: AsyncSession, slug: str, *, published_only: bool) -> Vendor:
    query = select(Vendor).where(Vendor.slug == slug)
    if published_only:
        query = query.where(Vendor.is_published)
    vendor = await session.scalar(query)
    if vendor is None:
        raise VendorNotFoundError(slug)
    return vendor


async def get_vendor(session: AsyncSession, slug: str, *, base_url: str | None) -> PublicVendor:
    vendor = await find_vendor(session, slug, published_only=True)
    pictures = await _pictures_by_vendor(session, [vendor.id])
    return public_view(vendor, pictures[vendor.id], base_url)


# --- Admin ---------------------------------------------------------------------------------------


async def admin_vendor(session: AsyncSession, vendor: Vendor, base_url: str | None) -> AdminVendor:
    pictures = await _pictures_by_vendor(session, [vendor.id])
    return admin_view(vendor, pictures[vendor.id], base_url)


async def admin_vendors(session: AsyncSession, *, base_url: str | None) -> list[AdminVendor]:
    vendors = list(await session.scalars(select(Vendor).order_by(*_PUBLIC_ORDER)))
    pictures = await _pictures_by_vendor(session, (v.id for v in vendors))
    return [admin_view(v, pictures[v.id], base_url) for v in vendors]


async def create_vendor(session: AsyncSession, data: VendorCreate) -> Vendor:
    """New vendors start unpublished. A slug that exists already is a 409 (DUPLICATE_ENTRY)."""
    vendor = Vendor(**data.model_dump())
    session.add(vendor)
    await session.flush()
    await session.refresh(vendor)  # server-side timestamps
    return vendor


async def patch_vendor(session: AsyncSession, slug: str, patch: VendorPatch) -> Vendor:
    vendor = await find_vendor(session, slug, published_only=False)
    for field, value in patch.model_dump(exclude_unset=True).items():
        setattr(vendor, field, value)
    await session.flush()
    await session.refresh(vendor)  # server-side updated_at
    return vendor


async def set_published(session: AsyncSession, slug: str, published: bool) -> Vendor:
    vendor = await find_vendor(session, slug, published_only=False)
    vendor.is_published = published
    await session.flush()
    return vendor


async def delete_vendor(session: AsyncSession, slug: str, confirm: str | None) -> list[str]:
    """Deletes the vendor and its picture rows; returns the file keys to delete after commit."""
    vendor = await find_vendor(session, slug, published_only=False)
    if confirm != slug:
        raise ConfirmationMismatchError(slug)
    keys = list(
        await session.scalars(
            select(VendorPicture.storage_key).where(VendorPicture.vendor_id == vendor.id)
        )
    )
    await session.delete(vendor)
    await session.flush()
    return [key for storage_key in keys for key in file_keys(storage_key)]


async def add_picture(
    session: AsyncSession,
    storage: PictureStorage,
    slug: str,
    data: bytes,
    *,
    is_logo: bool,
    caption: str | None,
) -> VendorPicture:
    if len(data) > MAX_UPLOAD_BYTES:
        raise PictureTooLargeError(MAX_UPLOAD_BYTES)
    vendor = await find_vendor(session, slug, published_only=False)
    if is_logo:
        logo_id = await session.scalar(
            select(VendorPicture.id).where(
                VendorPicture.vendor_id == vendor.id, VendorPicture.is_logo
            )
        )
        if logo_id is not None:
            raise VendorLogoExistsError(logo_id)
    else:
        count = await session.scalar(
            select(func.count())
            .select_from(VendorPicture)
            .where(VendorPicture.vendor_id == vendor.id, ~VendorPicture.is_logo)
        )
        if (count or 0) >= MAX_PHOTOS_PER_VENDOR:
            raise TooManyPicturesError(MAX_PHOTOS_PER_VENDOR, owner="vendor")

    processed, storage_key = await process_and_store(
        session, storage, data, VendorPicture, "vendor-pictures"
    )
    last_order = await session.scalar(
        select(func.max(VendorPicture.display_order)).where(VendorPicture.vendor_id == vendor.id)
    )
    picture = VendorPicture(
        vendor_id=vendor.id,
        storage_key=storage_key,
        is_logo=is_logo,
        caption=caption,
        width=processed.width,
        height=processed.height,
        display_order=0 if last_order is None else min(last_order + 1, _MAX_DISPLAY_ORDER),
    )
    session.add(picture)
    await session.flush()
    await session.refresh(picture)  # server-side created_at
    return picture


async def find_picture(session: AsyncSession, slug: str, picture_id: int) -> VendorPicture:
    vendor = await find_vendor(session, slug, published_only=False)
    picture = await session.scalar(
        select(VendorPicture).where(
            VendorPicture.id == picture_id, VendorPicture.vendor_id == vendor.id
        )
    )
    if picture is None:
        raise PictureNotFoundError(picture_id)
    return picture


async def patch_picture(
    session: AsyncSession, slug: str, picture_id: int, patch: PicturePatch
) -> VendorPicture:
    picture = await find_picture(session, slug, picture_id)
    for field, value in patch.model_dump(exclude_unset=True).items():
        setattr(picture, field, value)
    await session.flush()
    return picture


async def delete_picture(session: AsyncSession, slug: str, picture_id: int) -> list[str]:
    """Deletes the row; returns its file keys to delete from storage after the commit."""
    picture = await find_picture(session, slug, picture_id)
    await session.delete(picture)
    await session.flush()
    return file_keys(picture.storage_key)
