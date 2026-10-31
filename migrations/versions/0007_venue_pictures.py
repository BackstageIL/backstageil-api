"""venue pictures: the building and its entrance (BSIL-69)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-31 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. A new table only: backward-compatible for blue-green."""
    op.create_table(
        "venue_pictures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("caption", sa.String(length=300), nullable=True),
        sa.Column("width", sa.SmallInteger(), nullable=False),
        sa.Column("height", sa.SmallInteger(), nullable=False),
        sa.Column("display_order", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        "ix_venue_pictures_venue_id_display_order",
        "venue_pictures",
        ["venue_id", "display_order"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_venue_pictures_venue_id_display_order", table_name="venue_pictures")
    op.drop_table("venue_pictures")
