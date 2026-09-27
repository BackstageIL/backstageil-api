from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.db.types import str_enum

if TYPE_CHECKING:
    from app.db.models.venue import Venue


class RecommendationCategory(StrEnum):
    FOOD = "food"
    COFFEE = "coffee"
    BAR = "bar"
    HOTEL = "hotel"
    PARKING = "parking"
    MUSIC_STORE = "music_store"
    PHARMACY = "pharmacy"
    SUPERMARKET = "supermarket"
    OTHER = "other"


class Recommendation(TimestampMixin, Base):
    """A place near a venue that crews need (food, parking, hotel...). Can be sponsored."""

    __tablename__ = "recommendations"
    __table_args__ = (
        Index(
            "ix_recommendations_venue_id_category_display_order",
            "venue_id",
            "category",
            "display_order",
        ),
        CheckConstraint("distance_m >= 0", name="distance_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"))
    category: Mapped[RecommendationCategory] = mapped_column(
        str_enum(RecommendationCategory, "recommendation_category")
    )
    name: Mapped[str] = mapped_column(String(150))
    address: Mapped[str | None] = mapped_column(String(200))
    website: Mapped[str | None] = mapped_column(String(300))
    phone: Mapped[str | None] = mapped_column(String(30))  # business phone only
    note: Mapped[str | None] = mapped_column(Text)
    distance_m: Mapped[int | None] = mapped_column(Integer)
    is_sponsored: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    sponsored_until: Mapped[date | None] = mapped_column(Date)
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    venue: Mapped["Venue"] = relationship(back_populates="recommendations", lazy="raise")
