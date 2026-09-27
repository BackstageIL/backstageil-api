"""baseline: empty starting point of the migration history (only creates alembic_version)

Revision ID: 0000
Revises:
Create Date: 2026-09-27 22:50:31.299969

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0000"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
