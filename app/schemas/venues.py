"""Public API response models for cities, venues and halls (read-only, published data only)."""

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.db.models import District, VenueType
from app.schemas.hall_fields import HallTechnicalFields, Meters


class _FromRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CityRef(_FromRow):
    slug: str
    name_en: str
    name_he: str
    district: District | None


class CityWithCount(CityRef):
    venue_count: int


class VenueSummary(_FromRow):
    slug: str
    name: str
    name_he: str | None
    venue_type: VenueType
    street_address: str | None
    street_address_he: str | None
    city: CityRef
    hall_count: int


class VenuePage(BaseModel):
    items: list[VenueSummary]
    total: int
    limit: int
    offset: int


class HallSummary(_FromRow):
    slug: str
    name: str
    name_he: str | None
    capacity_seated: int | None
    stage_width_m: Meters | None
    stage_depth_m: Meters | None


class VenueDetail(_FromRow):
    slug: str
    name: str
    name_he: str | None
    venue_type: VenueType
    street_address: str | None
    street_address_he: str | None
    website: str | None
    city: CityRef
    halls: list[HallSummary]


class VenueRef(_FromRow):
    slug: str
    name: str
    name_he: str | None
    street_address: str | None
    street_address_he: str | None
    city: CityRef


class HallDocument(HallTechnicalFields):
    """A hall's full technical document: flat technical fields + notes + particular extras."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    name_he: str | None
    venue: VenueRef
    field_notes: dict[str, str]
    extras: dict[str, Any]
    source: str | None
    last_verified_at: date | None
