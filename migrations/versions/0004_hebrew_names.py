"""hebrew names for venues and halls

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08 23:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. Nullable columns: backward-compatible for blue-green."""
    op.add_column("venues", sa.Column("name_he", sa.String(length=150), nullable=True))
    op.add_column("halls", sa.Column("name_he", sa.String(length=150), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("halls", "name_he")
    op.drop_column("venues", "name_he")
