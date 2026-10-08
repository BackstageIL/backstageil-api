"""Venue recommendations (places nearby that crews need): public list, admin view and edits."""

from datetime import date, datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.db.models import RecommendationCategory
from app.schemas.venue_import import SafeText

# Business phone of the place: digits, spaces and dashes, optional leading +
BusinessPhone = Annotated[str, Field(pattern=r"^\+?\d[\d -]{5,26}\d$", max_length=30)]


class Recommendation(BaseModel):
    """Public view. `is_sponsored` is true only while the sponsorship is running."""

    id: int
    category: RecommendationCategory
    name: str
    address: str | None
    website: str | None
    phone: str | None
    note: str | None
    distance_m: int | None
    is_sponsored: bool


class AdminRecommendation(BaseModel):
    """Admin view: stored values, plus whether the sponsorship is running today."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    category: RecommendationCategory
    name: str
    address: str | None
    website: str | None
    phone: str | None
    note: str | None
    distance_m: int | None
    is_sponsored: bool
    sponsored_until: date | None
    sponsored_now: bool
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RecommendationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: RecommendationCategory
    name: SafeText = Field(min_length=2, max_length=150)
    address: SafeText | None = Field(default=None, max_length=200)
    website: HttpUrl | None = Field(default=None, max_length=300)
    phone: BusinessPhone | None = None
    note: SafeText | None = Field(default=None, max_length=1000)
    distance_m: int | None = Field(default=None, ge=0, le=100_000)
    is_sponsored: bool = False
    sponsored_until: date | None = None  # last day of the sponsorship (Israel time)
    display_order: int = Field(default=0, ge=0, le=32767)
    is_active: bool = True


_REQUIRED = ("category", "name", "is_sponsored", "display_order", "is_active")


class RecommendationPatch(BaseModel):
    """Only the fields sent are changed; null clears an optional field."""

    model_config = ConfigDict(extra="forbid")

    category: RecommendationCategory | None = None
    name: SafeText | None = Field(default=None, min_length=2, max_length=150)
    address: SafeText | None = Field(default=None, max_length=200)
    website: HttpUrl | None = Field(default=None, max_length=300)
    phone: BusinessPhone | None = None
    note: SafeText | None = Field(default=None, max_length=1000)
    distance_m: int | None = Field(default=None, ge=0, le=100_000)
    is_sponsored: bool | None = None
    sponsored_until: date | None = None
    display_order: int | None = Field(default=None, ge=0, le=32767)
    is_active: bool | None = None

    @model_validator(mode="after")
    def required_fields_are_not_cleared(self) -> Self:
        cleared = [f for f in _REQUIRED if f in self.model_fields_set and getattr(self, f) is None]
        if cleared:
            raise ValueError(f"cannot be null: {', '.join(cleared)}")
        return self
