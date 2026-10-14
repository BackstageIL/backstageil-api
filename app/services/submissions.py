"""
Submissions from the website (BSIL-58).

Anyone can send information; nothing is published from here: the admin reviews each submission.
Spam is handled without third parties: a hidden trap field and a minimum fill time drop bots
quietly, and each connection may send a few submissions per hour (counted by an anonymous
keyed hash of the address that changes every day; the address itself is never stored).
Files are checked by their content, photos are re-encoded without metadata (EXIF, GPS), and
everything goes to a private store.
"""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InvalidSubmissionFileError,
    PictureStorageUnavailableError,
    SubmissionNotFoundError,
    SubmissionsNotConfiguredError,
    SubmissionTooLargeError,
    TooManySubmissionsError,
)
from app.core.logger import get_logger
from app.db.models import Submission, SubmissionStatus
from app.schemas.submissions import AdminSubmission, SubmissionFile, SubmissionForm
from app.services.picture_storage import PictureStorage, delete_files_quietly

logger = get_logger(__name__)

MAX_FILES = 5
MAX_TOTAL_BYTES = 4_000_000  # Vercel Functions accept requests up to 4.5 MB
MIN_FILL_SECONDS = 3
MAX_PER_HOUR = 5
MAX_EMAILS_PER_DAY = 30

_ZIP = b"PK\x03\x04"
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_OFFICE_BY_EXTENSION = {
    "docx": (_ZIP, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "xlsx": (_ZIP, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "doc": (_OLE, "application/msword"),
    "xls": (_OLE, "application/vnd.ms-excel"),
}
_IMAGE_FORMATS = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}


@dataclass(frozen=True)
class CheckedFile:
    name: str
    data: bytes
    content_type: str


def client_hash(secret: str, address: str, day: date) -> str:
    """Anonymous code of a connection for one day: a keyed hash, not reversible without the key."""
    message = f"{day.isoformat()}|{address}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def looks_like_a_bot(form: SubmissionForm, now_ms: int) -> bool:
    """The hidden field was filled in, or the form was sent faster than a person can."""
    if form.website.strip():
        return True
    return form.started_at is not None and now_ms - form.started_at < MIN_FILL_SECONDS * 1000


def safe_name(name: str, fallback: str) -> str:
    """A file name without folders or unusual characters, at most 80 characters."""
    base = re.split(r"[\\/]", name or "")[-1]
    cleaned = re.sub(r"[^\w.\- ]+", "_", base, flags=re.UNICODE).strip(" ._")
    return (cleaned or fallback)[:80]


def _strip_image(data: bytes) -> tuple[bytes, str, str] | None:
    """Photos are re-encoded upright and without metadata; None when it isn't an image."""
    try:
        with Image.open(BytesIO(data)) as image:
            image_format = image.format or ""
            if image_format not in _IMAGE_FORMATS:
                return None
            upright = ImageOps.exif_transpose(image)
            if image_format == "JPEG" and upright.mode not in ("RGB", "L"):
                upright = upright.convert("RGB")
            out = BytesIO()
            upright.save(out, image_format, quality=90)
    except UnidentifiedImageError, OSError, ValueError:
        return None
    content_type, extension = _IMAGE_FORMATS[image_format]
    return out.getvalue(), content_type, extension


def check_file(name: str, data: bytes, index: int) -> CheckedFile:
    """Accept photos, PDF, Word and Excel by their content, not by the name the browser sent."""
    display = safe_name(name, f"file-{index + 1}")
    image = _strip_image(data)
    if image is not None:
        cleaned, content_type, extension = image
        stem = display.rsplit(".", 1)[0] if "." in display else display
        return CheckedFile(f"{stem}.{extension}", cleaned, content_type)
    if data.startswith(b"%PDF"):
        return CheckedFile(display, data, "application/pdf")
    extension = display.rsplit(".", 1)[-1].lower() if "." in display else ""
    office = _OFFICE_BY_EXTENSION.get(extension)
    if office is not None and data.startswith(office[0]):
        return CheckedFile(display, data, office[1])
    raise InvalidSubmissionFileError(display)


def check_files(files: list[tuple[str, bytes]]) -> list[CheckedFile]:
    if len(files) > MAX_FILES or sum(len(data) for _, data in files) > MAX_TOTAL_BYTES:
        raise SubmissionTooLargeError(MAX_FILES, MAX_TOTAL_BYTES)
    return [check_file(name, data, i) for i, (name, data) in enumerate(files) if data]


async def recent_count(session: AsyncSession, hash_: str, now: datetime) -> int:
    query = select(func.count()).where(
        Submission.client_hash == hash_, Submission.created_at > now - timedelta(hours=1)
    )
    return (await session.execute(query)).scalar_one()


async def emails_sent_today(session: AsyncSession, now: datetime) -> int:
    start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    query = select(func.count()).where(Submission.notified, Submission.created_at >= start)
    return (await session.execute(query)).scalar_one()


async def create_submission(
    session: AsyncSession,
    storage: PictureStorage | None,
    form: SubmissionForm,
    files: list[CheckedFile],
    hash_: str,
    now: datetime,
) -> Submission:
    if await recent_count(session, hash_, now) >= MAX_PER_HOUR:
        raise TooManySubmissionsError()
    if files and storage is None:
        raise SubmissionsNotConfiguredError()

    stored: list[dict[str, Any]] = []
    folder = f"submissions/{now:%Y-%m-%d}/{secrets.token_hex(12)}"
    try:
        for index, file in enumerate(files):
            if storage is None:  # checked above; keeps the type checker sure
                raise SubmissionsNotConfiguredError()
            key = f"{folder}/{index + 1}-{file.name}"
            await storage.put(key, file.data, file.content_type)
            stored.append(
                {
                    "key": key,
                    "name": file.name,
                    "content_type": file.content_type,
                    "size": len(file.data),
                }
            )
    except PictureStorageUnavailableError as exc:
        await delete_files_quietly(storage, [f["key"] for f in stored])
        raise SubmissionsNotConfiguredError() from exc

    submission = Submission(
        kind=form.kind,
        venue_slug=form.venue,
        hall_slug=form.hall,
        venue_name=form.venue_name,
        message=form.message.strip(),
        contact_name=form.contact_name,
        contact_email=form.contact_email,
        files=stored,
        client_hash=hash_,
        status=SubmissionStatus.NEW,
    )
    session.add(submission)
    await session.flush()
    return submission


# --- Admin ----------------------------------------------------------------------------------------


def to_admin(submission: Submission) -> AdminSubmission:
    return AdminSubmission(
        id=submission.id,
        created_at=submission.created_at,
        kind=submission.kind,
        venue_slug=submission.venue_slug,
        hall_slug=submission.hall_slug,
        venue_name=submission.venue_name,
        message=submission.message,
        contact_name=submission.contact_name,
        contact_email=submission.contact_email,
        files=[
            SubmissionFile(index=i, name=f["name"], content_type=f["content_type"], size=f["size"])
            for i, f in enumerate(submission.files)
        ],
        status=submission.status,
        notified=submission.notified,
        handled_at=submission.handled_at,
    )


async def list_submissions(
    session: AsyncSession, status: SubmissionStatus | None, limit: int
) -> list[Submission]:
    query = select(Submission).order_by(Submission.created_at.desc()).limit(limit)
    if status is not None:
        query = query.where(Submission.status == status)
    return list((await session.execute(query)).scalars())


async def get_submission(session: AsyncSession, submission_id: int) -> Submission:
    submission = await session.get(Submission, submission_id)
    if submission is None:
        raise SubmissionNotFoundError(submission_id)
    return submission


def file_of(submission: Submission, index: int) -> dict[str, Any]:
    if not 0 <= index < len(submission.files):
        raise SubmissionNotFoundError(submission.id, index)
    return submission.files[index]


async def set_status(
    session: AsyncSession, submission_id: int, status: SubmissionStatus, now: datetime
) -> Submission:
    """Handled or rejected: contact details are cleared (they were only kept to reply)."""
    submission = await get_submission(session, submission_id)
    submission.status = status
    if status is SubmissionStatus.NEW:
        submission.handled_at = None
    else:
        submission.handled_at = now
        submission.contact_name = None
        submission.contact_email = None
    await session.flush()
    return submission


async def delete_submission(session: AsyncSession, submission_id: int) -> list[str]:
    """Deletes the row; returns the file keys to delete from the store afterwards."""
    submission = await get_submission(session, submission_id)
    keys = [f["key"] for f in submission.files]
    await session.delete(submission)
    await session.flush()
    return keys
