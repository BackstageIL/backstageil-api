"""
Input models for importing verified venue data (one venue + one hall per item).

Used by scripts/load_venues.py now, and by the admin upload later (BSIL-21).
Any free text that looks like a phone number or an email is rejected: personal contact
details are never stored.
"""

import re
from datetime import date
from typing import Annotated, Any, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    PositiveInt,
    model_validator,
)

from app.db.models import VenueType
from app.schemas.hall_extras import HallExtras, HallFieldNotes
from app.schemas.hall_fields import TEXT_FIELDS, HallTechnicalFields

_PHONE = re.compile(r"\+?\d[\d\- ]{6,}\d")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", re.IGNORECASE)
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


def check_no_contact_details(text: str) -> str:
    if _PHONE.search(text) or _EMAIL.search(text):
        raise ValueError(
            "looks like a phone number or email (personal contact details are not stored)"
        )
    return text


SafeText = Annotated[str, AfterValidator(check_no_contact_details)]


class VenueImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=SLUG_PATTERN, max_length=150)
    name: SafeText = Field(min_length=2, max_length=150)
    city_code: PositiveInt  # official CBS locality code (cities.official_code)
    street_address: SafeText | None = Field(default=None, max_length=200)
    venue_type: VenueType
    website: HttpUrl | None = None


class HallImport(HallTechnicalFields):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=SLUG_PATTERN, max_length=80)
    name: SafeText = Field(min_length=2, max_length=150)

    extras: HallExtras = HallExtras({})
    field_notes: HallFieldNotes = HallFieldNotes({})

    source: SafeText | None = Field(default=None, max_length=200)
    last_verified_at: date | None = None

    @model_validator(mode="after")
    def texts_have_no_contact_details(self) -> Self:
        check_hall_texts(self, self.field_notes, self.extras)
        return self


def check_hall_texts(
    hall: HallTechnicalFields, field_notes: HallFieldNotes | None, extras: HallExtras | None
) -> None:
    """Reject contact details in every free-text field, field note and extra of a hall."""
    texts: list[object] = [getattr(hall, name) for name in TEXT_FIELDS]
    if field_notes is not None:
        texts += list(field_notes.root.values())
    if extras is not None:
        for extra in extras.root.values():
            texts += [extra.label, extra.note, extra.value]
    for text in texts:
        if isinstance(text, str):
            check_no_contact_details(text)


class VenueImportItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sheet: str | None = None  # label from the source file, for reporting only
    venue: VenueImport
    hall: HallImport

    def hall_values(self) -> dict[str, Any]:
        """Hall columns ready for the database (JSON columns as plain dicts)."""
        values = self.hall.model_dump(exclude={"extras", "field_notes"})
        values["extras"] = self.hall.extras.model_dump(mode="json", exclude_none=True)
        values["field_notes"] = self.hall.field_notes.model_dump(mode="json")
        return values
