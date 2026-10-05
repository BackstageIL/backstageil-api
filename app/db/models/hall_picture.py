from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.hall import Hall


class HallPicture(Base):
    """A picture of a hall. The files live in object storage (Vercel Blob); this row points to them.

    `storage_key` is a prefix built from the content hash; each size is a file under it
    (`<storage_key>/large.webp`, `<storage_key>/thumb.webp`). width/height are of the large size.
    """

    __tablename__ = "hall_pictures"
    __table_args__ = (Index("ix_hall_pictures_hall_id_display_order", "hall_id", "display_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id", ondelete="CASCADE"))
    storage_key: Mapped[str] = mapped_column(String(300), unique=True)
    caption: Mapped[str | None] = mapped_column(String(300))
    width: Mapped[int] = mapped_column(SmallInteger)
    height: Mapped[int] = mapped_column(SmallInteger)
    display_order: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    hall: Mapped[Hall] = relationship(back_populates="pictures", lazy="raise")
