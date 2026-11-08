"""Vendors directory (BSIL-79): public view, admin view and admin edits."""

from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import District, VendorCategory
from app.schemas.pictures import AdminPicture, Picture
from app.schemas.recommendations import BusinessPhone
from app.schemas.venue_import import SLUG_PATTERN, SafeText

# A business email given by the vendor for publication (a plain shape check, no lookups)
BusinessEmail = Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$", max_length=254)]
Categories = Annotated[list[VendorCategory], Field(min_length=1, max_length=10)]
Districts = Annotated[list[District], Field(max_length=7)]


class Vendor(BaseModel):
    """Public view. `districts` empty = the whole country. `logo` is not repeated in `pictures`."""

    slug: str
    name: str
    name_he: str | None
    description: str | None
    description_he: str | None
    categories: list[VendorCategory]
    districts: list[District]
    phone: str | None
    email: str | None
    logo: Picture | None
    pictures: list[Picture]


class AdminVendor(BaseModel):
    """Admin view: stored values, unpublished vendors too, pictures with their storage keys."""

    slug: str
    name: str
    name_he: str | None
    description: str | None
    description_he: str | None
    categories: list[VendorCategory]
    districts: list[District]
    phone: str | None
    email: str | None
    is_published: bool
    display_order: int
    logo: AdminPicture | None
    pictures: list[AdminPicture]
    created_at: datetime
    updated_at: datetime


class VendorCreate(BaseModel):
    """Names and descriptions may not hold phones or emails: contact goes in phone / email."""

    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=SLUG_PATTERN, max_length=150)
    name: SafeText = Field(min_length=2, max_length=150)
    name_he: SafeText | None = Field(default=None, min_length=2, max_length=150)
    description: SafeText | None = Field(default=None, max_length=1000)
    description_he: SafeText | None = Field(default=None, max_length=1000)
    categories: Categories
    districts: Districts = []
    phone: BusinessPhone | None = None
    email: BusinessEmail | None = None
    display_order: int = Field(default=0, ge=0, le=32767)


_REQUIRED = ("name", "categories", "districts", "display_order")


class VendorPatch(BaseModel):
    """Only the fields sent are changed; null clears an optional field. The slug stays."""

    model_config = ConfigDict(extra="forbid")

    name: SafeText | None = Field(default=None, min_length=2, max_length=150)
    name_he: SafeText | None = Field(default=None, min_length=2, max_length=150)
    description: SafeText | None = Field(default=None, max_length=1000)
    description_he: SafeText | None = Field(default=None, max_length=1000)
    categories: Categories | None = None
    districts: Districts | None = None
    phone: BusinessPhone | None = None
    email: BusinessEmail | None = None
    display_order: int | None = Field(default=None, ge=0, le=32767)

    @model_validator(mode="after")
    def required_fields_are_not_cleared(self) -> Self:
        cleared = [f for f in _REQUIRED if f in self.model_fields_set and getattr(self, f) is None]
        if cleared:
            raise ValueError(f"cannot be null: {', '.join(cleared)}")
        return self
