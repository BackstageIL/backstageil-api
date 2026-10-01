"""hall technical document fields: common items promoted from extras to columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-01 21:35:37.103181

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. All new columns are nullable, so this is backward-compatible."""
    op.add_column("halls", sa.Column("case_storage", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("has_orchestra_pit", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("has_stairs_to_house", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("has_quick_change_area", sa.Boolean(), nullable=True))
    op.add_column(
        "halls", sa.Column("first_pipe_distance_m", sa.Numeric(precision=5, scale=2), nullable=True)
    )
    op.add_column("halls", sa.Column("foh_truss_possible", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("has_lighting_bridge", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("pa_flying_possible", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("truss_hanging_possible", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("has_masking", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("has_black_legs", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("house_pa", sa.String(length=200), nullable=True))
    op.add_column("halls", sa.Column("foh_position", sa.String(length=200), nullable=True))
    op.add_column("halls", sa.Column("follow_spot_positions", sa.SmallInteger(), nullable=True))
    op.add_column("halls", sa.Column("has_video_space", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("star_dressing_rooms", sa.SmallInteger(), nullable=True))
    op.add_column("halls", sa.Column("has_green_room", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("has_showers", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("has_artist_toilets", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("has_production_office", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("has_laundry", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("has_wifi", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("stage_screws_allowed", sa.Boolean(), nullable=True))
    op.add_column("halls", sa.Column("seat_kills", sa.Text(), nullable=True))
    op.add_column("halls", sa.Column("sightlines", sa.Text(), nullable=True))
    # Not detected by autogenerate: keep in sync with Hall.__table_args__
    op.create_check_constraint(
        op.f("ck_halls_document_values_non_negative"),
        "halls",
        "first_pipe_distance_m >= 0 AND follow_spot_positions >= 0 AND star_dressing_rooms >= 0",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_halls_document_values_non_negative"), "halls", type_="check")
    op.drop_column("halls", "sightlines")
    op.drop_column("halls", "seat_kills")
    op.drop_column("halls", "stage_screws_allowed")
    op.drop_column("halls", "has_wifi")
    op.drop_column("halls", "has_laundry")
    op.drop_column("halls", "has_production_office")
    op.drop_column("halls", "has_artist_toilets")
    op.drop_column("halls", "has_showers")
    op.drop_column("halls", "has_green_room")
    op.drop_column("halls", "star_dressing_rooms")
    op.drop_column("halls", "has_video_space")
    op.drop_column("halls", "follow_spot_positions")
    op.drop_column("halls", "foh_position")
    op.drop_column("halls", "house_pa")
    op.drop_column("halls", "has_black_legs")
    op.drop_column("halls", "has_masking")
    op.drop_column("halls", "truss_hanging_possible")
    op.drop_column("halls", "pa_flying_possible")
    op.drop_column("halls", "has_lighting_bridge")
    op.drop_column("halls", "foh_truss_possible")
    op.drop_column("halls", "first_pipe_distance_m")
    op.drop_column("halls", "has_quick_change_area")
    op.drop_column("halls", "has_stairs_to_house")
    op.drop_column("halls", "has_orchestra_pit")
    op.drop_column("halls", "case_storage")
