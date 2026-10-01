from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TimestampMixin
from app.db.types import str_enum

if TYPE_CHECKING:
    from app.db.models.hall_picture import HallPicture
    from app.db.models.venue import Venue


class StageFloor(StrEnum):
    WOOD = "wood"
    MARLEY = "marley"
    CONCRETE = "concrete"
    OTHER = "other"


class PipeType(StrEnum):
    COUNTERWEIGHT = "counterweight"
    MOTORIZED = "motorized"
    FIXED = "fixed"
    OTHER = "other"


class Hall(TimestampMixin, Base):
    """A stage/auditorium inside a venue, described like a venue technical document.

    Fixed columns hold what halls generally have (typed, filterable). `field_notes` holds a
    short factual note per fixed column ({"proscenium_width_m": "Adjustable, 12-16 m"}).
    `extras` is only for items particular to this hall ({key: {"label", "value", "note"}},
    see app.schemas.hall_extras).
    """

    __tablename__ = "halls"
    __table_args__ = (
        UniqueConstraint("venue_id", "slug", name="uq_halls_venue_id_slug"),
        Index("ix_halls_capacity_seated", "capacity_seated"),
        Index("ix_halls_stage_width_m", "stage_width_m"),
        Index("ix_halls_grid_height_m", "grid_height_m"),
        Index(
            "ix_halls_extras",
            "extras",
            postgresql_using="gin",
            postgresql_ops={"extras": "jsonb_path_ops"},
        ),
        Index("ix_halls_power_circuits_a", "power_circuits_a", postgresql_using="gin"),
        CheckConstraint(
            "capacity_seated >= 0 AND capacity_standing >= 0", name="capacity_non_negative"
        ),
        CheckConstraint(
            "stage_width_m > 0 AND stage_depth_m > 0 AND proscenium_width_m > 0"
            " AND grid_height_m > 0 AND foh_distance_m >= 0",
            name="dimensions_positive",
        ),
        CheckConstraint(
            "pipe_count >= 0 AND pipe_load_kg >= 0 AND dressing_rooms >= 0",
            name="counts_non_negative",
        ),
        CheckConstraint(
            "first_pipe_distance_m >= 0 AND follow_spot_positions >= 0"
            " AND star_dressing_rooms >= 0",
            name="document_values_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(150))

    # Sections follow a venue technical document. Every fixed column may carry a short
    # factual note in `field_notes`.

    # General
    capacity_seated: Mapped[int | None] = mapped_column(Integer)
    capacity_standing: Mapped[int | None] = mapped_column(Integer)
    # Access
    load_in_notes: Mapped[str | None] = mapped_column(Text)
    case_storage: Mapped[bool | None] = mapped_column(Boolean)
    # Stage (meters)
    stage_width_m: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    stage_depth_m: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    proscenium_width_m: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    stage_floor: Mapped[StageFloor | None] = mapped_column(str_enum(StageFloor, "stage_floor"))
    has_orchestra_pit: Mapped[bool | None] = mapped_column(Boolean)
    has_stairs_to_house: Mapped[bool | None] = mapped_column(Boolean)
    has_quick_change_area: Mapped[bool | None] = mapped_column(Boolean)
    # Rigging
    grid_height_m: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    pipe_count: Mapped[int | None] = mapped_column(SmallInteger)
    pipe_type: Mapped[PipeType | None] = mapped_column(str_enum(PipeType, "pipe_type"))
    pipe_load_kg: Mapped[int | None] = mapped_column(Integer)
    first_pipe_distance_m: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    foh_truss_possible: Mapped[bool | None] = mapped_column(Boolean)
    has_lighting_bridge: Mapped[bool | None] = mapped_column(Boolean)
    pa_flying_possible: Mapped[bool | None] = mapped_column(Boolean)
    truss_hanging_possible: Mapped[bool | None] = mapped_column(Boolean)
    # Masking
    has_masking: Mapped[bool | None] = mapped_column(Boolean)
    has_black_legs: Mapped[bool | None] = mapped_column(Boolean)
    # Power: available circuits in amps, e.g. [32, 63, 125]
    power_circuits_a: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), default=list, server_default=text("'{}'")
    )
    has_backup_generator: Mapped[bool | None] = mapped_column(Boolean)
    # Sound
    house_pa: Mapped[str | None] = mapped_column(String(200))
    foh_position: Mapped[str | None] = mapped_column(String(200))
    foh_distance_m: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    # Lighting / video
    follow_spot_positions: Mapped[int | None] = mapped_column(SmallInteger)
    has_video_space: Mapped[bool | None] = mapped_column(Boolean)
    # Backstage
    dressing_rooms: Mapped[int | None] = mapped_column(SmallInteger)
    star_dressing_rooms: Mapped[int | None] = mapped_column(SmallInteger)
    has_green_room: Mapped[bool | None] = mapped_column(Boolean)
    has_showers: Mapped[bool | None] = mapped_column(Boolean)
    has_artist_toilets: Mapped[bool | None] = mapped_column(Boolean)
    has_production_office: Mapped[bool | None] = mapped_column(Boolean)
    has_laundry: Mapped[bool | None] = mapped_column(Boolean)
    has_wifi: Mapped[bool | None] = mapped_column(Boolean)
    # Rules
    haze_allowed: Mapped[bool | None] = mapped_column(Boolean)
    stage_screws_allowed: Mapped[bool | None] = mapped_column(Boolean)
    # Seating
    seat_kills: Mapped[str | None] = mapped_column(Text)  # seats lost for FOH / follow spots
    sightlines: Mapped[str | None] = mapped_column(Text)
    # Notes (facts only)
    notes: Mapped[str | None] = mapped_column(Text)
    known_issues: Mapped[str | None] = mapped_column(Text)

    extras: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    field_notes: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )

    # Provenance
    source: Mapped[str | None] = mapped_column(String(200))
    last_verified_at: Mapped[date | None] = mapped_column(Date)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    venue: Mapped[Venue] = relationship(back_populates="halls", lazy="raise")
    pictures: Mapped[list[HallPicture]] = relationship(
        back_populates="hall",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="HallPicture.display_order",
    )
