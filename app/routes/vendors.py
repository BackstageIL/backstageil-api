from typing import Annotated

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import public_cache
from app.db.dependencies import get_session
from app.schemas.vendors import Vendor
from app.schemas.venue_import import SLUG_PATTERN
from app.services import pictures
from app.services import vendors as service

router = APIRouter(prefix="/vendors", tags=["Vendors"], dependencies=[Depends(public_cache)])

Session = Annotated[AsyncSession, Depends(get_session)]
VendorSlug = Annotated[str, Path(pattern=SLUG_PATTERN, max_length=150)]
PicturesBaseUrl = Annotated[str | None, Depends(pictures.get_pictures_base_url)]


@router.get(
    "",
    summary="List vendors",
    description="Published production vendors (sound, lighting, effects, staging...), in display "
    "order then by name. `districts` empty means the whole country. Phone and email are the "
    "vendor's own business contact, given for publication.",
)
async def list_vendors(session: Session, base_url: PicturesBaseUrl) -> list[Vendor]:
    return await service.published_vendors(session, base_url=base_url)


@router.get("/{vendor_slug}", summary="Vendor with its logo and photos")
async def get_vendor(
    session: Session, base_url: PicturesBaseUrl, vendor_slug: VendorSlug
) -> Vendor:
    return await service.get_vendor(session, vendor_slug, base_url=base_url)
