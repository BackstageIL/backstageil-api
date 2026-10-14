"""Public endpoint for the website's contribution form (BSIL-58)."""

import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import PicturesNotConfiguredError, SubmissionTooLargeError
from app.core.logger import get_logger
from app.core.security import client_address
from app.db.dependencies import get_session
from app.schemas.submissions import SubmissionForm, SubmissionReceived
from app.services import submissions
from app.services.notifications import SubmissionNotifier, get_notifier
from app.services.picture_storage import PrivateStorage, VercelBlobStorage

logger = get_logger(__name__)

router = APIRouter(prefix="/submissions", tags=["Submissions"])


def get_submission_storage(request: Request) -> PrivateStorage | None:
    """Route dependency: the PRIVATE store for submitted files, or None (text only)."""
    state = request.app.state
    settings: Settings = state.settings
    if state.submission_storage is None and settings.submissions_blob_token is not None:
        try:
            state.submission_storage = VercelBlobStorage(
                settings.submissions_blob_token.get_secret_value(), access="private"
            )
        except PicturesNotConfiguredError:
            logger.warning("SUBMISSIONS_BLOB_TOKEN is not a Vercel Blob read-write token")
    storage: PrivateStorage | None = state.submission_storage
    return storage


def hash_secret(request: Request) -> str:
    """Key for the anonymous connection codes: a server-side secret that never leaves the API."""
    settings: Settings = request.app.state.settings
    secret = settings.admin_api_key_hash or request.app.state.fallback_hash_secret
    return str(secret)


Session = Annotated[AsyncSession, Depends(get_session)]
Storage = Annotated[PrivateStorage | None, Depends(get_submission_storage)]
Notifier = Annotated[SubmissionNotifier | None, Depends(get_notifier)]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Send information about a venue",
    description=(
        "Multipart form from the website. Nothing is published: the admin reviews every "
        f"submission. Up to {submissions.MAX_FILES} files and "
        f"{submissions.MAX_TOTAL_BYTES // 1_000_000} MB in total (photos, PDF, Word, Excel); "
        "photos are stored without metadata. The message and venue name must not contain "
        "phone numbers or email addresses; contact details are optional."
    ),
)
async def submit(
    request: Request,
    response: Response,
    session: Session,
    storage: Storage,
    notifier: Notifier,
    kind: Annotated[str, Form()],
    message: Annotated[str, Form()],
    rights: Annotated[str | None, Form(description="Must be true")] = None,
    venue: Annotated[str | None, Form()] = None,
    hall: Annotated[str | None, Form()] = None,
    venue_name: Annotated[str | None, Form()] = None,
    contact_name: Annotated[str | None, Form()] = None,
    contact_email: Annotated[str | None, Form()] = None,
    website: Annotated[str, Form(description="Leave empty")] = "",
    started_at: Annotated[int | None, Form(description="When the form was opened (ms)")] = None,
    files: Annotated[list[UploadFile], File(description="Optional files")] = [],  # noqa: B006
) -> SubmissionReceived:
    response.headers["Cache-Control"] = "no-store"
    # One model for the text fields (FastAPI can't combine a form model with file parts)
    fields = {
        "kind": kind,
        "message": message,
        "rights": rights,
        "venue": venue or None,
        "hall": hall or None,
        "venue_name": venue_name or None,
        "contact_name": contact_name or None,
        "contact_email": contact_email or None,
        "website": website,
        "started_at": started_at,
    }
    try:
        form = SubmissionForm.model_validate(fields)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False)) from exc
    if submissions.looks_like_a_bot(form, int(time.time() * 1000)):
        # Answer as if it worked, so bots don't learn what gave them away
        return SubmissionReceived()

    raw: list[tuple[str, bytes]] = []
    total = 0
    for upload in files[: submissions.MAX_FILES + 1]:
        data = await upload.read(submissions.MAX_TOTAL_BYTES + 1 - total)
        total += len(data)
        raw.append((upload.filename or "", data))
        if total > submissions.MAX_TOTAL_BYTES:
            raise SubmissionTooLargeError(submissions.MAX_FILES, submissions.MAX_TOTAL_BYTES)
    checked = submissions.check_files(raw)

    now = datetime.now(UTC)
    code = submissions.client_hash(hash_secret(request), client_address(request), now.date())
    submission = await submissions.create_submission(session, storage, form, checked, code, now)
    await session.commit()

    if notifier is not None:
        if await submissions.emails_sent_today(session, now) < submissions.MAX_EMAILS_PER_DAY:
            if await notifier.notify(submission):
                submission.notified = True
                await session.commit()
        else:
            logger.warning(
                "Daily submission email limit reached; submission %s saved", submission.id
            )
    return SubmissionReceived()
