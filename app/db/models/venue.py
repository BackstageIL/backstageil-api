from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Numeric, String, false, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.db.types import str_enum

if TYPE_CHECKING:
    from app.db.models.city import City
    from app.db.models.hall import Hall
    from app.db.models.recommendation import Recommendation


class VenueType(StrEnum):
    THEATER = "theater"
    CULTURE_HALL = "culture_hall"
    CONCERT_HALL = "concert_hall"
    CLUB = "club"
    ARENA = "arena"
    AMPHITHEATER = "amphitheater"
    OUTDOOR = "outdoor"
    OTHER = "other"


class Venue(TimestampMixin, Base):
    """A place (building/complex) in a city. Its halls hold the technical data."""

    __tablename__ = "venues"
    __table_args__ = (
        # The same name may exist in another city, or in the same city on another street.
        Index(
            "uq_venues_city_name_street",
            "city_id",
            text("lower(name)"),
            text("lower(coalesce(street_address, ''))"),
            unique=True,
        ),
        Index("ix_venues_city_id_venue_type", "city_id", "venue_type"),
        # Fuzzy / search-as-you-type on the name (pg_trgm)
        Index(
            "ix_venues_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(150), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    name_he: Mapped[str | None] = mapped_column(String(150))  # Hebrew name (BSIL-48)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id", ondelete="RESTRICT"))
    street_address: Mapped[str | None] = mapped_column(String(200))
    street_address_he: Mapped[str | None] = mapped_column(String(200))  # Hebrew (BSIL-50)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    website: Mapped[str | None] = mapped_column(String(300))
    venue_type: Mapped[VenueType] = mapped_column(str_enum(VenueType, "venue_type"))
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    city: Mapped[City] = relationship(back_populates="venues", lazy="raise")
    halls: Mapped[list[Hall]] = relationship(
        back_populates="venue", lazy="raise", cascade="all, delete-orphan", passive_deletes=True
    )
    recommendations: Mapped[list[Recommendation]] = relationship(
        back_populates="venue", lazy="raise", cascade="all, delete-orphan", passive_deletes=True
    )
