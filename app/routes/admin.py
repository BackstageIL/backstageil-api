"""Admin-only routes. Every route here requires the admin API key (X-API-Key)."""

from datetime import date
from typing import Annotated

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    Path,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import no_store
from app.core.security import require_admin
from app.db.dependencies import get_session
from app.db.models import District, RecommendationCategory, VenueType
from app.schemas.admin import (
    AdminHallDocument,
    AdminHallSummary,
    AdminVenueDetail,
    AdminVenuePage,
    AdminVenueSummary,
    HallPatch,
    ImportReport,
    PublishState,
    VenuePatch,
)
from app.schemas.health import HealthResponse
from app.schemas.pictures import AdminPicture, PicturePatch
from app.schemas.recommendations import (
    AdminRecommendation,
    RecommendationCreate,
    RecommendationPatch,
)
from app.schemas.venue_import import SLUG_PATTERN, SafeText, VenueImportItem
from app.services import admin_venues, pictures, recommendations, venues
from app.services.picture_storage import (
    PictureStorage,
    delete_files_quietly,
    get_optional_picture_storage,
    get_picture_storage,
)
from app.services.venue_import import import_items

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin), Depends(no_store)],
)

Session = Annotated[AsyncSession, Depends(get_session)]
VenueSlug = Annotated[str, Path(pattern=SLUG_PATTERN, max_length=150)]
HallSlug = Annotated[str, Path(pattern=SLUG_PATTERN, max_length=80)]
PictureId = Annotated[int, Path(ge=1)]
RecommendationId = Annotated[int, Path(ge=1)]
Today = Annotated[date, Depends(recommendations.israel_today)]
Storage = Annotated[PictureStorage, Depends(get_picture_storage)]
OptionalStorage = Annotated[PictureStorage | None, Depends(get_optional_picture_storage)]
PicturesBaseUrl = Annotated[str | None, Depends(pictures.get_pictures_base_url)]
Confirm = Annotated[str | None, Query(description="Repeat the slug to confirm the deletion")]
MAX_IMPORT_ITEMS = 200


@router.get(
    "/ping",
    summary="Check the admin key",
    description="Returns ok when X-API-Key is valid. Useful after setting or rotating the key.",
)
async def ping() -> HealthResponse:
    return HealthResponse()


# --- Bulk upload -------------------------------------------------------------------------------


@router.post(
    "/venues/import",
    summary="Upload verified venues (bulk)",
    description="Same JSON format as the loader file: a list of {venue, hall} items. "
    "`publish` is required: every venue and hall in the upload gets that visibility. "
    "All-or-nothing. With dry_run=true everything is checked and counted, nothing is saved.",
)
async def import_venues(
    session: Session,
    items: Annotated[list[VenueImportItem], Body(min_length=1, max_length=MAX_IMPORT_ITEMS)],
    publish: Annotated[bool, Query(description="Visibility of every uploaded venue and hall")],
    dry_run: bool = False,
) -> ImportReport:
    # All-or-nothing, explicitly: the whole batch runs in a savepoint that is rolled back on any
    # error (and always for a dry run), so a failing item can never leave earlier items behind.
    savepoint = await session.begin_nested()
    try:
        report = await import_items(session, items, publish=publish, dry_run=dry_run)
    except Exception:
        await savepoint.rollback()
        raise
    if dry_run:
        await savepoint.rollback()
        return report
    await savepoint.commit()
    await session.commit()
    return report


# --- Read (including unpublished) --------------------------------------------------------------


@router.get("/venues", summary="List venues (including unpublished)")
async def list_venues(
    session: Session,
    published: bool | None = None,
    q: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    city: Annotated[str | None, Query(pattern=SLUG_PATTERN)] = None,
    district: District | None = None,
    venue_type: Annotated[VenueType | None, Query(alias="type")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminVenuePage:
    filters = venues.VenueFilters(
        q=q, city=city, district=district, venue_type=venue_type, published=published
    )
    items, total = await venues.list_venues(
        session, filters, limit=limit, offset=offset, published_only=False, model=AdminVenueSummary
    )
    return AdminVenuePage(items=items, total=total, limit=limit, offset=offset)


@router.get("/venues/{venue_slug}", summary="Venue with all its halls (admin view)")
async def get_venue(session: Session, venue_slug: VenueSlug) -> AdminVenueDetail:
    return await venues.get_venue(
        session,
        venue_slug,
        published_only=False,
        model=AdminVenueDetail,
        hall_model=AdminHallSummary,
    )


@router.get("/venues/{venue_slug}/halls/{hall_slug}", summary="Hall document (admin view)")
async def get_hall(
    session: Session, venue_slug: VenueSlug, hall_slug: HallSlug
) -> AdminHallDocument:
    return await venues.get_hall(
        session, venue_slug, hall_slug, published_only=False, model=AdminHallDocument
    )


# --- Edit ----------------------------------------------------------------------------------------


@router.patch(
    "/venues/{venue_slug}",
    summary="Edit a venue",
    description="Only the fields sent are changed. Visibility is not changed.",
)
async def patch_venue(
    session: Session, venue_slug: VenueSlug, patch: VenuePatch
) -> AdminVenueDetail:
    await admin_venues.patch_venue(session, venue_slug, patch)
    await session.commit()
    return await get_venue(session, venue_slug)


@router.patch(
    "/venues/{venue_slug}/halls/{hall_slug}",
    summary="Edit a hall",
    description="Only the fields sent are changed; null clears a field; field_notes and extras, "
    "when sent, replace the whole map. Visibility is not changed.",
)
async def patch_hall(
    session: Session, venue_slug: VenueSlug, hall_slug: HallSlug, patch: HallPatch
) -> AdminHallDocument:
    hall = await admin_venues.patch_hall(session, venue_slug, hall_slug, patch)
    await session.commit()
    return await venues.hall_document(session, hall, model=AdminHallDocument)


# --- Visibility ----------------------------------------------------------------------------------


@router.post("/venues/{venue_slug}/publish", summary="Publish a venue")
async def publish_venue(session: Session, venue_slug: VenueSlug) -> PublishState:
    state = await admin_venues.set_venue_published(session, venue_slug, True)
    await session.commit()
    return state


@router.post("/venues/{venue_slug}/unpublish", summary="Unpublish a venue (hides its halls too)")
async def unpublish_venue(session: Session, venue_slug: VenueSlug) -> PublishState:
    state = await admin_venues.set_venue_published(session, venue_slug, False)
    await session.commit()
    return state


@router.post("/venues/{venue_slug}/halls/{hall_slug}/publish", summary="Publish a hall")
async def publish_hall(
    session: Session, venue_slug: VenueSlug, hall_slug: HallSlug
) -> PublishState:
    state = await admin_venues.set_hall_published(session, venue_slug, hall_slug, True)
    await session.commit()
    return state


@router.post("/venues/{venue_slug}/halls/{hall_slug}/unpublish", summary="Unpublish a hall")
async def unpublish_hall(
    session: Session, venue_slug: VenueSlug, hall_slug: HallSlug
) -> PublishState:
    state = await admin_venues.set_hall_published(session, venue_slug, hall_slug, False)
    await session.commit()
    return state


# --- Pictures ----------------------------------------------------------------------------------

PICTURES = "/venues/{venue_slug}/halls/{hall_slug}/pictures"


@router.get(PICTURES, summary="Hall pictures (admin view)")
async def list_pictures(
    session: Session, base_url: PicturesBaseUrl, venue_slug: VenueSlug, hall_slug: HallSlug
) -> list[AdminPicture]:
    return await pictures.list_pictures(
        session,
        venue_slug,
        hall_slug,
        base_url=base_url,
        published_only=False,
        model=AdminPicture,
    )


@router.post(
    PICTURES,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a hall picture",
    description="Multipart upload of one JPEG, PNG or WebP file (max 4 MB). It is turned upright, "
    "stripped of all metadata (EXIF, GPS) and stored as WebP in a large and a thumbnail size. "
    f"Up to {pictures.MAX_PICTURES_PER_HALL} pictures per hall; new pictures go last.",
)
async def upload_picture(
    session: Session,
    storage: Storage,
    base_url: PicturesBaseUrl,
    venue_slug: VenueSlug,
    hall_slug: HallSlug,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP, max 4 MB")],
    caption: Annotated[SafeText | None, Form(max_length=300)] = None,
) -> AdminPicture:
    pictures.require_base_url(base_url)
    data = await file.read(pictures.MAX_UPLOAD_BYTES + 1)  # one byte more detects a larger file
    picture = await pictures.add_picture(session, storage, venue_slug, hall_slug, data, caption)
    await session.commit()
    return pictures.to_model(picture, base_url, AdminPicture)


@router.patch(
    PICTURES + "/{picture_id}",
    summary="Edit a picture's caption or display order",
    description="Only the fields sent are changed; caption null clears it.",
)
async def patch_picture(
    session: Session,
    base_url: PicturesBaseUrl,
    venue_slug: VenueSlug,
    hall_slug: HallSlug,
    picture_id: PictureId,
    patch: PicturePatch,
) -> AdminPicture:
    picture = await pictures.patch_picture(session, venue_slug, hall_slug, picture_id, patch)
    await session.commit()
    return pictures.to_model(picture, base_url, AdminPicture)


@router.delete(
    PICTURES + "/{picture_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a picture permanently (row and files)",
)
async def delete_picture(
    session: Session,
    storage: Storage,
    venue_slug: VenueSlug,
    hall_slug: HallSlug,
    picture_id: PictureId,
) -> Response:
    picture_files = await pictures.delete_picture(session, venue_slug, hall_slug, picture_id)
    await session.commit()
    await delete_files_quietly(storage, picture_files)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})


# --- Recommendations ---------------------------------------------------------------------------

RECOMMENDATIONS = "/venues/{venue_slug}/recommendations"


@router.get(RECOMMENDATIONS, summary="Venue recommendations (including inactive)")
async def list_recommendations(
    session: Session,
    today: Today,
    venue_slug: VenueSlug,
    category: RecommendationCategory | None = None,
) -> list[AdminRecommendation]:
    rows = await recommendations.list_recommendations(
        session, venue_slug, today=today, category=category, public=False
    )
    return [recommendations.admin_view(row, today) for row in rows]


@router.post(
    RECOMMENDATIONS,
    status_code=status.HTTP_201_CREATED,
    summary="Add a recommendation",
    description="`phone` is the place's business phone; names, addresses and notes may not hold "
    "phone numbers or emails. A sponsorship runs while is_sponsored is set, until the end of "
    "sponsored_until (Israel time; empty = no end).",
)
async def create_recommendation(
    session: Session, today: Today, venue_slug: VenueSlug, data: RecommendationCreate
) -> AdminRecommendation:
    row = await recommendations.create_recommendation(session, venue_slug, data)
    await session.commit()
    return recommendations.admin_view(row, today)


@router.patch(
    RECOMMENDATIONS + "/{recommendation_id}",
    summary="Edit a recommendation",
    description="Only the fields sent are changed; null clears an optional field. "
    "is_active=false hides it from the public list without deleting it.",
)
async def patch_recommendation(
    session: Session,
    today: Today,
    venue_slug: VenueSlug,
    recommendation_id: RecommendationId,
    patch: RecommendationPatch,
) -> AdminRecommendation:
    row = await recommendations.patch_recommendation(session, venue_slug, recommendation_id, patch)
    await session.commit()
    return recommendations.admin_view(row, today)


@router.delete(
    RECOMMENDATIONS + "/{recommendation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a recommendation permanently",
)
async def delete_recommendation(
    session: Session, venue_slug: VenueSlug, recommendation_id: RecommendationId
) -> Response:
    await recommendations.delete_recommendation(session, venue_slug, recommendation_id)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})


# --- Delete --------------------------------------------------------------------------------------


@router.delete(
    "/venues/{venue_slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a venue permanently",
    description="Also deletes its halls, pictures (rows and files) and recommendations. "
    "Requires ?confirm=<venue_slug>.",
)
async def delete_venue(
    session: Session, storage: OptionalStorage, venue_slug: VenueSlug, confirm: Confirm = None
) -> Response:
    picture_files = await pictures.file_keys_of(session, venue_slug)
    await admin_venues.delete_venue(session, venue_slug, confirm)
    await session.commit()
    await delete_files_quietly(storage, picture_files)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})


@router.delete(
    "/venues/{venue_slug}/halls/{hall_slug}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a hall permanently",
    description="Requires ?confirm=<hall_slug>.",
)
async def delete_hall(
    session: Session,
    storage: OptionalStorage,
    venue_slug: VenueSlug,
    hall_slug: HallSlug,
    confirm: Confirm = None,
) -> Response:
    picture_files = await pictures.file_keys_of(session, venue_slug, hall_slug)
    await admin_venues.delete_hall(session, venue_slug, hall_slug, confirm)
    await session.commit()
    await delete_files_quietly(storage, picture_files)
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers={"Cache-Control": "no-store"})
