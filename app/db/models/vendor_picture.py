from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.vendor import Vendor


class VendorPicture(Base):
    """A vendor's logo (at most one) or a photo of its equipment and work.

    Same shape as VenuePicture, files under their own prefix (`vendor-pictures/<hash>`).
    """

    __tablename__ = "vendor_pictures"
    __table_args__ = (
        Index("ix_vendor_pictures_vendor_id_display_order", "vendor_id", "display_order"),
        Index(
            "uq_vendor_pictures_one_logo",
            "vendor_id",
            unique=True,
            postgresql_where=text("is_logo"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id", ondelete="CASCADE"))
    storage_key: Mapped[str] = mapped_column(String(300), unique=True)
    is_logo: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    caption: Mapped[str | None] = mapped_column(String(300))
    width: Mapped[int] = mapped_column(SmallInteger)
    height: Mapped[int] = mapped_column(SmallInteger)
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    vendor: Mapped[Vendor] = relationship(back_populates="pictures", lazy="raise")
