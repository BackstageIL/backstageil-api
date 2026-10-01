"""
Validation for the hall JSON columns `extras` and `field_notes`.

field_notes = {"proscenium_width_m": "Adjustable, 12-16 m"}   # a short fact per fixed column
extras      = {"stage_cameras": {"label": "Stage cameras",    # items particular to one hall
                                 "note": "4 cameras on stage must be covered"}}

Anything most halls have is a fixed column on `halls`, not an extra. EXTRA_SPECS lists the few
optional items that recur occasionally (label/type defined here); any other snake_case key is
allowed as long as it carries its own label.
"""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

from app.db.models import Hall


class ExtraCategory(StrEnum):
    STAGE = "stage"
    RIGGING = "rigging"
    SOUND = "sound"
    BACKSTAGE = "backstage"
    ACCESS = "access"
    OTHER = "other"


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


EXTRA_SPECS: dict[str, ExtraSpec] = {
    "stage_shape": ExtraSpec("Stage shape", ExtraCategory.STAGE, ValueType.TEXT),
    "stage_extension": ExtraSpec("Stage extension", ExtraCategory.STAGE, ValueType.TEXT),
}

# Columns that are not technical facts, or are free text themselves: no field notes for them.
_NOT_NOTED = {
    "id",
    "venue_id",
    "slug",
    "name",
    "extras",
    "field_notes",
    "source",
    "last_verified_at",
    "is_published",
    "created_at",
    "updated_at",
    "load_in_notes",
    "notes",
    "known_issues",
    "seat_kills",
    "sightlines",
    "house_pa",
    "foh_position",
}

# Every technical fixed column of `halls` may carry a note (derived from the model).
FIELD_NOTE_KEYS: frozenset[str] = frozenset(
    column.name for column in Hall.__table__.columns if column.name not in _NOT_NOTED
)

_KEY = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
_PYTHON_TYPES: dict[ValueType, tuple[type, ...]] = {
    ValueType.BOOL: (bool,),
    ValueType.INT: (int,),
    ValueType.FLOAT: (int, float),
    ValueType.TEXT: (str,),
}


class ExtraValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=2, max_length=80)
    value: bool | int | float | str | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def value_or_note(self) -> Self:
        if self.value is None and not self.note:
            raise ValueError("an extra needs a value, a note, or both")
        return self


class HallExtras(RootModel[dict[str, ExtraValue]]):
    """Registered keys are type-checked; other keys must be snake_case and carry a label."""

    @model_validator(mode="after")
    def keys_and_types(self) -> Self:
        for key, extra in self.root.items():
            if key in FIELD_NOTE_KEYS or key in Hall.__table__.columns:
                raise ValueError(f"'{key}' is a fixed hall column, not an extra")
            spec = EXTRA_SPECS.get(key)
            if spec is None:
                if not _KEY.match(key):
                    raise ValueError(f"extra key '{key}' must be snake_case")
                if not extra.label:
                    raise ValueError(f"extra '{key}' is not registered and needs a label")
                continue
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
    """Validates `field_notes`: notes only for technical fixed hall columns."""

    @model_validator(mode="after")
    def keys_are_fixed_columns(self) -> Self:
        unknown = set(self.root) - FIELD_NOTE_KEYS
        if unknown:
            raise ValueError(f"no technical hall column named {sorted(unknown)}")
        return self
