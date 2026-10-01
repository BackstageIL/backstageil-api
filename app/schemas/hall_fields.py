"""
Technical fields of a hall, shared by the import schema (input) and the API (output),
so both always match the `halls` table. Sections follow a venue technical document.
"""

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, NonNegativeInt, PlainSerializer, PositiveInt

from app.db.models import PipeType, StageFloor

# Exact decimals inside the app; plain JSON numbers in API responses (e.g. 24.0, not "24.00").
_AS_NUMBER = PlainSerializer(float, return_type=float, when_used="json")
Meters = Annotated[Decimal, Field(gt=0, max_digits=5, decimal_places=2), _AS_NUMBER]
MetersOrZero = Annotated[Decimal, Field(ge=0, max_digits=5, decimal_places=2), _AS_NUMBER]

# Free-text fields: checked for contact details on import (see HallImport).
TEXT_FIELDS = (
    "load_in_notes",
    "house_pa",
    "foh_position",
    "seat_kills",
    "sightlines",
    "notes",
    "known_issues",
)


class HallTechnicalFields(BaseModel):
    # General
    capacity_seated: NonNegativeInt | None = None
    capacity_standing: NonNegativeInt | None = None
    # Access
    load_in_notes: str | None = None
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
    house_pa: str | None = Field(default=None, max_length=200)
    foh_position: str | None = Field(default=None, max_length=200)
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
    seat_kills: str | None = None
    sightlines: str | None = None
    # Notes (facts only)
    notes: str | None = None
    known_issues: str | None = None
