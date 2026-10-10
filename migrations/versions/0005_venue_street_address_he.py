"""hebrew street address for venues

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-10 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. Nullable column: backward-compatible for blue-green."""
    op.add_column("venues", sa.Column("street_address_he", sa.String(length=200), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("venues", "street_address_he")
