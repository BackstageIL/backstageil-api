"""Submissions sent from the website (BSIL-58): the public form and the admin views."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import SubmissionKind, SubmissionStatus
from app.schemas.venue_import import SLUG_PATTERN, SafeText

# Simple shape check only: the address is optional and used solely to reply
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"


class SubmissionForm(BaseModel):
    """The website form's text fields (files come as separate multipart parts)."""

    model_config = ConfigDict(extra="ignore")

    kind: SubmissionKind
    # Free text, checked like venue data: no phone numbers or emails (no personal details)
    message: Annotated[SafeText, Field(min_length=3, max_length=5000)]
    venue: Annotated[str | None, Field(pattern=SLUG_PATTERN, max_length=150)] = None
    hall: Annotated[str | None, Field(pattern=SLUG_PATTERN, max_length=80)] = None
    venue_name: Annotated[SafeText | None, Field(min_length=2, max_length=200)] = None
    contact_name: Annotated[str | None, Field(min_length=2, max_length=100)] = None
    contact_email: Annotated[str | None, Field(pattern=EMAIL_PATTERN, max_length=200)] = None
    # "I'm allowed to share this, and it has no personal details": must be ticked
    rights: Literal[True, "true", "on", "1"]
    # Spam traps: a hidden field people never fill in, and when the form was opened (ms)
    website: str = ""
    started_at: int | None = None


class SubmissionReceived(BaseModel):
    status: Literal["received"] = "received"


class SubmissionFile(BaseModel):
    index: int
    name: str
    content_type: str
    size: int


class AdminSubmission(BaseModel):
    id: int
    created_at: datetime
    kind: SubmissionKind
    venue_slug: str | None
    hall_slug: str | None
    venue_name: str | None
    message: str
    contact_name: str | None
    contact_email: str | None
    files: list[SubmissionFile]
    status: SubmissionStatus
    notified: bool
    handled_at: datetime | None


class SubmissionPatch(BaseModel):
    """Handled or rejected clears the contact details; new reopens it."""

    model_config = ConfigDict(extra="forbid")

    status: SubmissionStatus
