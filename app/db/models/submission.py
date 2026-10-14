from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Boolean, DateTime, Index, String, Text, false, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.db.types import str_enum


class SubmissionKind(StrEnum):
    CORRECTION = "correction"
    DOCUMENT = "document"  # tech rider, fly plan, drawings
    PHOTOS = "photos"
    NEARBY = "nearby"  # a place near a venue
    NEW_VENUE = "new_venue"
    OTHER = "other"


class SubmissionStatus(StrEnum):
    NEW = "new"
    HANDLED = "handled"
    REJECTED = "rejected"


class Submission(TimestampMixin, Base):
    """Information a visitor sent through the website (BSIL-58). Never public: the admin reviews
    it and decides what goes into the venue data. Contact details are optional and are cleared
    once the submission is handled or rejected."""

    __tablename__ = "submissions"
    __table_args__ = (
        Index("ix_submissions_status_created_at", "status", "created_at"),
        Index("ix_submissions_client_hash_created_at", "client_hash", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[SubmissionKind] = mapped_column(str_enum(SubmissionKind, "submission_kind"))
    # Free references to the page it was sent from (no foreign keys: slugs can change)
    venue_slug: Mapped[str | None] = mapped_column(String(150))
    hall_slug: Mapped[str | None] = mapped_column(String(80))
    venue_name: Mapped[str | None] = mapped_column(String(200))  # e.g. a venue we're missing
    message: Mapped[str] = mapped_column(Text)
    contact_name: Mapped[str | None] = mapped_column(String(100))
    contact_email: Mapped[str | None] = mapped_column(String(200))
    # [{"key": ..., "name": ..., "content_type": ..., "size": ...}] in the private store
    files: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    # Anonymous per-day code of the sender's connection (keyed hash, never the address itself);
    # only used to limit how many submissions one connection can send
    client_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[SubmissionStatus] = mapped_column(
        str_enum(SubmissionStatus, "submission_status"), default=SubmissionStatus.NEW
    )
    notified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
