"""vendors directory: vendors and their pictures (BSIL-79)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-08 22:08:06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. New tables only: backward-compatible for blue-green."""
    op.create_table(
        "vendors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=150), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("name_he", sa.String(length=150), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("description_he", sa.Text(), nullable=True),
        sa.Column("categories", sa.ARRAY(sa.String(length=20)), nullable=False),
        sa.Column(
            "districts",
            sa.ARRAY(sa.String(length=20)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("is_published", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("display_order", sa.SmallInteger(), server_default="0", nullable=False),
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
        sa.CheckConstraint(
            "categories <@ ARRAY['sound', 'lighting', 'video', 'dj_effects', 'staging', "
            "'backline', 'power', 'transport', 'crew', 'other']::varchar[]",
            name=op.f("ck_vendors_categories_known"),
        ),
        sa.CheckConstraint(
            "districts <@ ARRAY['north', 'haifa', 'center', 'tel_aviv', 'jerusalem', 'south', "
            "'judea_samaria']::varchar[]",
            name=op.f("ck_vendors_districts_known"),
        ),
        sa.CheckConstraint(
            "cardinality(categories) > 0", name=op.f("ck_vendors_categories_not_empty")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vendors")),
        sa.UniqueConstraint("slug", name=op.f("uq_vendors_slug")),
    )
    op.create_table(
        "vendor_pictures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("is_logo", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["vendor_id"],
            ["vendors.id"],
            name=op.f("fk_vendor_pictures_vendor_id_vendors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vendor_pictures")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_vendor_pictures_storage_key")),
    )
    op.create_index(
        "ix_vendor_pictures_vendor_id_display_order",
        "vendor_pictures",
        ["vendor_id", "display_order"],
        unique=False,
    )
    op.create_index(
        "uq_vendor_pictures_one_logo",
        "vendor_pictures",
        ["vendor_id"],
        unique=True,
        postgresql_where=sa.text("is_logo"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "uq_vendor_pictures_one_logo",
        table_name="vendor_pictures",
        postgresql_where=sa.text("is_logo"),
    )
    op.drop_index("ix_vendor_pictures_vendor_id_display_order", table_name="vendor_pictures")
    op.drop_table("vendor_pictures")
    op.drop_table("vendors")
