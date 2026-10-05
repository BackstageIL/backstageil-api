"""hall picture dimensions (width/height of the large size)

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05 22:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. NOT NULL is safe for blue-green: hall_pictures is empty and the running
    version has no code that writes it (uploads arrive with this release)."""
    op.add_column("hall_pictures", sa.Column("width", sa.SmallInteger(), nullable=False))
    op.add_column("hall_pictures", sa.Column("height", sa.SmallInteger(), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("hall_pictures", "height")
    op.drop_column("hall_pictures", "width")
