"""Hall picture models: public gallery items, admin view and admin edits."""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.venue_import import SafeText


class Picture(BaseModel):
    """A hall picture, with URLs usable directly in <img> (WebP, no metadata)."""

    id: int
    caption: str | None
    width: int  # of the large size
    height: int
    url: str  # large size, longest edge up to 1600 px
    thumbnail_url: str  # longest edge up to 400 px


class AdminPicture(Picture):
    display_order: int
    storage_key: str
    created_at: datetime


class PicturePatch(BaseModel):
    """Only the fields sent are changed; caption null clears it."""

    model_config = ConfigDict(extra="forbid")

    caption: SafeText | None = Field(default=None, max_length=300)
    display_order: int | None = Field(default=None, ge=0, le=32767)

    @model_validator(mode="after")
    def display_order_is_not_cleared(self) -> Self:
        if "display_order" in self.model_fields_set and self.display_order is None:
            raise ValueError("display_order cannot be null")
        return self
