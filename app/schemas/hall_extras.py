"""
Registry and validation for hall `extras` and `field_notes` (JSONB columns on halls).

extras      = {"green_room": {"value": true, "note": "huge"}, "showers": {"value": true}}
field_notes = {"proscenium_width_m": "12-16 m, adjustable"}

To add a new extra field: add one entry to EXTRA_SPECS. No database migration is needed.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator


class ExtraCategory(StrEnum):
    STAGE = "stage"
    RIGGING = "rigging"
    POWER_VIDEO = "power_video"
    FOH = "foh"
    MASKING = "masking"
    BACKSTAGE = "backstage"
    RULES = "rules"


class ValueType(StrEnum):
    BOOL = "bool"
    INT = "int"
    FLOAT = "float"
    TEXT = "text"


@dataclass(frozen=True)
class ExtraSpec:
    label: str
    category: ExtraCategory
    value_type: ValueType
    unit: str | None = None


_S, _R, _PV, _F, _M, _B, _RU = (
    ExtraCategory.STAGE,
    ExtraCategory.RIGGING,
    ExtraCategory.POWER_VIDEO,
    ExtraCategory.FOH,
    ExtraCategory.MASKING,
    ExtraCategory.BACKSTAGE,
    ExtraCategory.RULES,
)
_BOOL, _TEXT = ValueType.BOOL, ValueType.TEXT

EXTRA_SPECS: dict[str, ExtraSpec] = {
    # Stage
    "stage_stairs": ExtraSpec("Stairs to the stage", _S, _BOOL),
    "backstage_work_light": ExtraSpec("Backstage work light", _S, _BOOL),
    "quick_change": ExtraSpec("Quick-change area", _S, _BOOL),
    # Rigging
    "foh_truss": ExtraSpec("FOH truss", _R, _BOOL),
    "pa_hanging": ExtraSpec("PA hanging possible", _R, _BOOL),
    "truss_hanging": ExtraSpec("Truss hanging possible (LED / video / lights)", _R, _BOOL),
    # Power & video
    "onstage_video_space": ExtraSpec("On-stage video space", _PV, _BOOL),
    # FOH
    "follow_spot_positions": ExtraSpec("Follow-spot positions", _F, _TEXT),
    "seats_to_remove": ExtraSpec("Seats to remove (FOH / follow spots)", _F, _TEXT),
    "sightline_issues": ExtraSpec("Sightline issues", _F, _TEXT),
    # Masking
    "masking": ExtraSpec("Masking", _M, _BOOL),
    "black_legs": ExtraSpec("Black legs", _M, _BOOL),
    # Backstage
    "star_dressing_room": ExtraSpec("Star dressing room", _B, _BOOL),
    "green_room": ExtraSpec("Green room", _B, _BOOL),
    "mirrors_full_body": ExtraSpec("Full-body mirrors", _B, _BOOL),
    "mirrors_makeup": ExtraSpec("Make-up mirrors", _B, _BOOL),
    "tables": ExtraSpec("Tables", _B, _BOOL),
    "chairs": ExtraSpec("Chairs", _B, _BOOL),
    "clothes_hangers": ExtraSpec("Clothes hangers / rails", _B, _BOOL),
    "showers": ExtraSpec("Showers", _B, _BOOL),
    "artist_toilets": ExtraSpec("Artist toilets", _B, _BOOL),
    "production_office": ExtraSpec("Production office", _B, _BOOL),
    "washer_dryer": ExtraSpec("Washing machine / dryer", _B, _BOOL),
    "internet": ExtraSpec("Internet / Wi-Fi", _B, _BOOL),
    "empty_case_storage": ExtraSpec("Empty case storage", _B, _BOOL),
    # Rules
    "stage_screws_allowed": ExtraSpec("Screwing into the stage allowed", _RU, _BOOL),
}

# Fixed hall columns that may carry a free-text note in `field_notes`.
FIELD_NOTE_KEYS: frozenset[str] = frozenset(
    {
        "capacity_seated",
        "capacity_standing",
        "stage_width_m",
        "stage_depth_m",
        "proscenium_width_m",
        "stage_floor",
        "grid_height_m",
        "pipe_count",
        "pipe_type",
        "pipe_load_kg",
        "power_circuits_a",
        "has_backup_generator",
        "haze_allowed",
        "foh_distance_m",
        "dressing_rooms",
    }
)

_PYTHON_TYPES: dict[ValueType, tuple[type, ...]] = {
    ValueType.BOOL: (bool,),
    ValueType.INT: (int,),
    ValueType.FLOAT: (int, float),
    ValueType.TEXT: (str,),
}


class ExtraValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: bool | int | float | str | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def value_or_note(self) -> Self:
        if self.value is None and not self.note:
            raise ValueError("an extra needs a value, a note, or both")
        return self


class HallExtras(RootModel[dict[str, ExtraValue]]):
    """Validates the `extras` JSON: only registered keys, each value of its declared type."""

    @model_validator(mode="after")
    def keys_and_types_match_registry(self) -> Self:
        for key, extra in self.root.items():
            spec = EXTRA_SPECS.get(key)
            if spec is None:
                raise ValueError(f"unknown extra '{key}'")
            if extra.value is None:
                continue
            allowed = _PYTHON_TYPES[spec.value_type]
            # bool is a subclass of int: never accept True/False for numeric extras
            is_bool = isinstance(extra.value, bool)
            if not isinstance(extra.value, allowed) or (
                is_bool and spec.value_type is not ValueType.BOOL
            ):
                raise ValueError(f"extra '{key}' must be of type {spec.value_type}")
        return self


class HallFieldNotes(RootModel[dict[str, str]]):
    """Validates `field_notes`: notes only for known fixed hall columns."""

    @model_validator(mode="after")
    def keys_are_fixed_columns(self) -> Self:
        unknown = set(self.root) - FIELD_NOTE_KEYS
        if unknown:
            raise ValueError(f"no fixed hall column named {sorted(unknown)}")
        return self
