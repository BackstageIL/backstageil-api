from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.venue import Venue


class VenuePicture(Base):
    """A picture of the venue itself (the building, the entrance), shown on the venue page only.

    Same shape as HallPicture. Files are under their own prefix (`venue-pictures/<hash>`), so a
    venue picture never shares files with a hall picture and deleting one never removes the other's.
    The caption carries the photographer credit that a free license requires.
    """

    __tablename__ = "venue_pictures"
    __table_args__ = (
        Index("ix_venue_pictures_venue_id_display_order", "venue_id", "display_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"))
    storage_key: Mapped[str] = mapped_column(String(300), unique=True)
    caption: Mapped[str | None] = mapped_column(String(300))
    width: Mapped[int] = mapped_column(SmallInteger)
    height: Mapped[int] = mapped_column(SmallInteger)
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    venue: Mapped[Venue] = relationship(back_populates="pictures", lazy="raise")
