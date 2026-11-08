from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ARRAY, Boolean, CheckConstraint, SmallInteger, String, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.db.models.city import District

if TYPE_CHECKING:
    from app.db.models.vendor_picture import VendorPicture


class VendorCategory(StrEnum):
    SOUND = "sound"
    LIGHTING = "lighting"
    VIDEO = "video"  # screens, projection, LED walls
    DJ_EFFECTS = "dj_effects"  # DJ booths, smoke, CO2, confetti, special effects
    STAGING = "staging"  # stages, truss, rigging
    BACKLINE = "backline"
    POWER = "power"  # generators, distribution
    TRANSPORT = "transport"
    CREW = "crew"  # technicians, stagehands
    OTHER = "other"


def _all_in(column: str, enum_cls: type[StrEnum]) -> str:
    """CHECK that every value of an array column is one of the enum's values."""
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return f"{column} <@ ARRAY[{values}]::varchar[]"


class Vendor(TimestampMixin, Base):
    """A production vendor (sound, lighting, effects...) listed in the vendors directory (BSIL-79).

    Kept apart from venues and halls: a vendor is never tied to, or recommended by, a venue.
    Contact details are the vendor's own business phone and email, given for publication;
    names and descriptions never hold contact details (checked by the schemas).
    """

    __tablename__ = "vendors"
    __table_args__ = (
        CheckConstraint(_all_in("categories", VendorCategory), name="categories_known"),
        CheckConstraint("cardinality(categories) > 0", name="categories_not_empty"),
        CheckConstraint(_all_in("districts", District), name="districts_known"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(150), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    name_he: Mapped[str | None] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)
    description_he: Mapped[str | None] = mapped_column(Text)
    categories: Mapped[list[str]] = mapped_column(ARRAY(String(20)))
    # Regions served; empty = the whole country
    districts: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), server_default=text("'{}'::varchar[]")
    )
    phone: Mapped[str | None] = mapped_column(String(30))  # business phone, given for publication
    email: Mapped[str | None] = mapped_column(String(254))  # business email, given for publication
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")

    pictures: Mapped[list[VendorPicture]] = relationship(
        back_populates="vendor",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="VendorPicture.display_order",
    )
