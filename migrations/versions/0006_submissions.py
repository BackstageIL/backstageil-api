"""submissions sent from the website (BSIL-58)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-14 21:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. A new table only: backward-compatible for blue-green."""
    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "correction",
                "document",
                "photos",
                "nearby",
                "new_venue",
                "other",
                name="submission_kind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("venue_slug", sa.String(length=150), nullable=True),
        sa.Column("hall_slug", sa.String(length=80), nullable=True),
        sa.Column("venue_name", sa.String(length=200), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("contact_name", sa.String(length=100), nullable=True),
        sa.Column("contact_email", sa.String(length=200), nullable=True),
        sa.Column(
            "files",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("client_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "new",
                "handled",
                "rejected",
                name="submission_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("notified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_submissions")),
    )
    op.create_index(
        "ix_submissions_client_hash_created_at",
        "submissions",
        ["client_hash", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_submissions_status_created_at", "submissions", ["status", "created_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_submissions_status_created_at", table_name="submissions")
    op.drop_index("ix_submissions_client_hash_created_at", table_name="submissions")
    op.drop_table("submissions")
