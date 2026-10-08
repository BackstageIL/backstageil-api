"""Admin API models: import report, partial edits, publish state and admin views."""

from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, PositiveInt, model_validator

from app.db.models import VenueType
from app.schemas.hall_extras import HallExtras, HallFieldNotes
from app.schemas.hall_fields import HallTechnicalFields
from app.schemas.venue_import import SafeText, check_hall_texts
from app.schemas.venues import HallDocument, HallSummary, VenueDetail, VenueSummary


class ImportReport(BaseModel):
    items: int
    venues_created: int
    venues_updated: int
    halls_created: int
    halls_updated: int
    dry_run: bool


class VenuePatch(BaseModel):
    """Only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")

    name: SafeText | None = Field(default=None, min_length=2, max_length=150)
    name_he: SafeText | None = Field(default=None, min_length=2, max_length=150)
    street_address: SafeText | None = Field(default=None, max_length=200)
    venue_type: VenueType | None = None
    website: HttpUrl | None = None
    city_code: PositiveInt | None = None


class HallPatch(HallTechnicalFields):
    """Only the fields sent are changed; an explicit null clears a field.
    `field_notes` / `extras`, when sent, replace the whole map."""

    model_config = ConfigDict(extra="forbid")

    name: SafeText | None = Field(default=None, min_length=2, max_length=150)
    name_he: SafeText | None = Field(default=None, min_length=2, max_length=150)
    field_notes: HallFieldNotes | None = None
    extras: HallExtras | None = None
    source: SafeText | None = Field(default=None, max_length=200)
    last_verified_at: date | None = None

    @model_validator(mode="after")
    def texts_have_no_contact_details(self) -> Self:
        check_hall_texts(self, self.field_notes, self.extras)
        return self


class SiteRebuildState(BaseModel):
    status: Literal["triggered"] = "triggered"


class PublishState(BaseModel):
    slug: str
    is_published: bool


class AdminVenueSummary(VenueSummary):
    is_published: bool


class AdminVenuePage(BaseModel):
    items: list[AdminVenueSummary]
    total: int
    limit: int
    offset: int


class AdminHallSummary(HallSummary):
    is_published: bool


class AdminVenueDetail(VenueDetail):
    halls: list[AdminHallSummary]  # type: ignore[assignment]
    is_published: bool


class AdminHallDocument(HallDocument):
    is_published: bool
