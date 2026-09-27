from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import str_enum

if TYPE_CHECKING:
    from app.db.models.venue import Venue


class District(StrEnum):
    NORTH = "north"
    HAIFA = "haifa"
    CENTER = "center"
    TEL_AVIV = "tel_aviv"
    JERUSALEM = "jerusalem"
    SOUTH = "south"
    JUDEA_SAMARIA = "judea_samaria"


class LocalityType(StrEnum):
    CITY = "city"
    LOCAL_COUNCIL = "local_council"
    KIBBUTZ = "kibbutz"
    MOSHAV = "moshav"
    OTHER = "other"


class City(Base):
    """An Israeli locality, seeded from the official localities list (official_code)."""

    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True)
    official_code: Mapped[int] = mapped_column(unique=True)
    name_en: Mapped[str] = mapped_column(String(100))
    name_he: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    district: Mapped[District | None] = mapped_column(str_enum(District, "district"), index=True)
    locality_type: Mapped[LocalityType] = mapped_column(
        str_enum(LocalityType, "locality_type"), default=LocalityType.OTHER
    )
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))

    venues: Mapped[list["Venue"]] = relationship(back_populates="city", lazy="raise")
