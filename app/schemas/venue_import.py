"""
Input models for importing verified venue data (one venue + one hall per item).

Used by scripts/load_venues.py now, and by the admin upload later (BSIL-21).
Any free text that looks like a phone number or an email is rejected: personal contact
details are never stored.
"""

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    NonNegativeInt,
    PositiveInt,
    model_validator,
)

from app.db.models import PipeType, StageFloor, VenueType
from app.schemas.hall_extras import HallExtras, HallFieldNotes

_PHONE = re.compile(r"\+?\d[\d\- ]{6,}\d")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", re.IGNORECASE)
_SLUG = r"^[a-z0-9]+(-[a-z0-9]+)*$"


def check_no_contact_details(text: str) -> str:
    if _PHONE.search(text) or _EMAIL.search(text):
        raise ValueError(
            "looks like a phone number or email (personal contact details are not stored)"
        )
    return text


SafeText = Annotated[str, AfterValidator(check_no_contact_details)]
Meters = Annotated[Decimal, Field(gt=0, max_digits=5, decimal_places=2)]
MetersOrZero = Annotated[Decimal, Field(ge=0, max_digits=5, decimal_places=2)]


class VenueImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=_SLUG, max_length=150)
    name: SafeText = Field(min_length=2, max_length=150)
    city_code: PositiveInt  # official CBS locality code (cities.official_code)
    street_address: SafeText | None = Field(default=None, max_length=200)
    venue_type: VenueType
    website: HttpUrl | None = None


class HallImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=_SLUG, max_length=80)
    name: SafeText = Field(min_length=2, max_length=150)

    # General
    capacity_seated: NonNegativeInt | None = None
    capacity_standing: NonNegativeInt | None = None
    # Access
    load_in_notes: SafeText | None = None
    case_storage: bool | None = None
    # Stage
    stage_width_m: Meters | None = None
    stage_depth_m: Meters | None = None
    proscenium_width_m: Meters | None = None
    stage_floor: StageFloor | None = None
    has_orchestra_pit: bool | None = None
    has_stairs_to_house: bool | None = None
    has_quick_change_area: bool | None = None
    # Rigging
    grid_height_m: Meters | None = None
    pipe_count: NonNegativeInt | None = None
    pipe_type: PipeType | None = None
    pipe_load_kg: NonNegativeInt | None = None
    first_pipe_distance_m: MetersOrZero | None = None
    foh_truss_possible: bool | None = None
    has_lighting_bridge: bool | None = None
    pa_flying_possible: bool | None = None
    truss_hanging_possible: bool | None = None
    # Masking
    has_masking: bool | None = None
    has_black_legs: bool | None = None
    # Power
    power_circuits_a: list[PositiveInt] = []
    has_backup_generator: bool | None = None
    # Sound
    house_pa: SafeText | None = Field(default=None, max_length=200)
    foh_position: SafeText | None = Field(default=None, max_length=200)
    foh_distance_m: MetersOrZero | None = None
    # Lighting / video
    follow_spot_positions: NonNegativeInt | None = None
    has_video_space: bool | None = None
    # Backstage
    dressing_rooms: NonNegativeInt | None = None
    star_dressing_rooms: NonNegativeInt | None = None
    has_green_room: bool | None = None
    has_showers: bool | None = None
    has_artist_toilets: bool | None = None
    has_production_office: bool | None = None
    has_laundry: bool | None = None
    has_wifi: bool | None = None
    # Rules
    haze_allowed: bool | None = None
    stage_screws_allowed: bool | None = None
    # Seating
    seat_kills: SafeText | None = None
    sightlines: SafeText | None = None
    # Notes (facts only)
    notes: SafeText | None = None
    known_issues: SafeText | None = None

    extras: HallExtras = HallExtras({})
    field_notes: HallFieldNotes = HallFieldNotes({})

    source: SafeText | None = Field(default=None, max_length=200)
    last_verified_at: date | None = None

    @model_validator(mode="after")
    def json_texts_have_no_contact_details(self) -> Self:
        texts: list[str] = list(self.field_notes.root.values())
        for extra in self.extras.root.values():
            texts += [t for t in (extra.label, extra.note, extra.value) if isinstance(t, str)]
        for text in texts:
            check_no_contact_details(text)
        return self


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
