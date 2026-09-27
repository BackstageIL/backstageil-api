"""initial schema: cities, venues, halls, hall_pictures, recommendations

Revision ID: 0001
Revises: 0000
Create Date: 2026-09-27 22:55:42.155288

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = "0000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Trigram index on venues.name (search-as-you-type) needs pg_trgm
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "cities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("official_code", sa.Integer(), nullable=False),
        sa.Column("name_en", sa.String(length=100), nullable=False),
        sa.Column("name_he", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column(
            "district",
            sa.Enum(
                "north",
                "haifa",
                "center",
                "tel_aviv",
                "jerusalem",
                "south",
                "judea_samaria",
                name="district",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column(
            "locality_type",
            sa.Enum(
                "city",
                "local_council",
                "kibbutz",
                "moshav",
                "other",
                name="locality_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cities")),
        sa.UniqueConstraint("official_code", name=op.f("uq_cities_official_code")),
        sa.UniqueConstraint("slug", name=op.f("uq_cities_slug")),
    )
    op.create_index(op.f("ix_cities_district"), "cities", ["district"], unique=False)
    op.create_table(
        "venues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=150), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("street_address", sa.String(length=200), nullable=True),
        sa.Column("latitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("longitude", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("website", sa.String(length=300), nullable=True),
        sa.Column(
            "venue_type",
            sa.Enum(
                "theater",
                "culture_hall",
                "concert_hall",
                "club",
                "arena",
                "amphitheater",
                "outdoor",
                "other",
                name="venue_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("is_published", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["city_id"], ["cities.id"], name=op.f("fk_venues_city_id_cities"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_venues")),
        sa.UniqueConstraint("slug", name=op.f("uq_venues_slug")),
    )
    op.create_index(
        "ix_venues_city_id_venue_type", "venues", ["city_id", "venue_type"], unique=False
    )
    op.create_index(
        "ix_venues_name_trgm",
        "venues",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "uq_venues_city_name_street",
        "venues",
        [
            "city_id",
            sa.literal_column("lower(name)"),
            sa.literal_column("lower(coalesce(street_address, ''))"),
        ],
        unique=True,
    )
    op.create_table(
        "halls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("capacity_seated", sa.Integer(), nullable=True),
        sa.Column("capacity_standing", sa.Integer(), nullable=True),
        sa.Column("stage_width_m", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("stage_depth_m", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("proscenium_width_m", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column(
            "stage_floor",
            sa.Enum(
                "wood",
                "marley",
                "concrete",
                "other",
                name="stage_floor",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("grid_height_m", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("pipe_count", sa.SmallInteger(), nullable=True),
        sa.Column(
            "pipe_type",
            sa.Enum(
                "counterweight",
                "motorized",
                "fixed",
                "other",
                name="pipe_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=True,
        ),
        sa.Column("pipe_load_kg", sa.Integer(), nullable=True),
        sa.Column(
            "power_circuits_a",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("has_backup_generator", sa.Boolean(), nullable=True),
        sa.Column("haze_allowed", sa.Boolean(), nullable=True),
        sa.Column("foh_distance_m", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("dressing_rooms", sa.SmallInteger(), nullable=True),
        sa.Column("load_in_notes", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("known_issues", sa.Text(), nullable=True),
        sa.Column(
            "extras",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "field_notes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=200), nullable=True),
        sa.Column("last_verified_at", sa.Date(), nullable=True),
        sa.Column("is_published", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
            "capacity_seated >= 0 AND capacity_standing >= 0",
            name=op.f("ck_halls_capacity_non_negative"),
        ),
        sa.CheckConstraint(
            "pipe_count >= 0 AND pipe_load_kg >= 0 AND dressing_rooms >= 0",
            name=op.f("ck_halls_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "stage_width_m > 0 AND stage_depth_m > 0 AND proscenium_width_m > 0"
            " AND grid_height_m > 0 AND foh_distance_m >= 0",
            name=op.f("ck_halls_dimensions_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["venue_id"], ["venues.id"], name=op.f("fk_halls_venue_id_venues"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_halls")),
        sa.UniqueConstraint("venue_id", "slug", name="uq_halls_venue_id_slug"),
    )
    op.create_index("ix_halls_capacity_seated", "halls", ["capacity_seated"], unique=False)
    op.create_index(
        "ix_halls_extras",
        "halls",
        ["extras"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"extras": "jsonb_path_ops"},
    )
    op.create_index("ix_halls_grid_height_m", "halls", ["grid_height_m"], unique=False)
    op.create_index(
        "ix_halls_power_circuits_a",
        "halls",
        ["power_circuits_a"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index("ix_halls_stage_width_m", "halls", ["stage_width_m"], unique=False)
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
                "food",
                "coffee",
                "bar",
                "hotel",
                "parking",
                "music_store",
                "pharmacy",
                "supermarket",
                "other",
                name="recommendation_category",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("address", sa.String(length=200), nullable=True),
        sa.Column("website", sa.String(length=300), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("distance_m", sa.Integer(), nullable=True),
        sa.Column("is_sponsored", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sponsored_until", sa.Date(), nullable=True),
        sa.Column("display_order", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
            "distance_m >= 0", name=op.f("ck_recommendations_distance_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["venue_id"],
            ["venues.id"],
            name=op.f("fk_recommendations_venue_id_venues"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendations")),
    )
    op.create_index(
        "ix_recommendations_venue_id_category_display_order",
        "recommendations",
        ["venue_id", "category", "display_order"],
        unique=False,
    )
    op.create_table(
        "hall_pictures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hall_id", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("caption", sa.String(length=300), nullable=True),
        sa.Column("display_order", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hall_id"],
            ["halls.id"],
            name=op.f("fk_hall_pictures_hall_id_halls"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hall_pictures")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_hall_pictures_storage_key")),
    )
    op.create_index(
        "ix_hall_pictures_hall_id_display_order",
        "hall_pictures",
        ["hall_id", "display_order"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema. The pg_trgm extension is left installed (harmless, may be shared)."""
    op.drop_index("ix_hall_pictures_hall_id_display_order", table_name="hall_pictures")
    op.drop_table("hall_pictures")
    op.drop_index(
        "ix_recommendations_venue_id_category_display_order", table_name="recommendations"
    )
    op.drop_table("recommendations")
    op.drop_index("ix_halls_stage_width_m", table_name="halls")
    op.drop_index("ix_halls_power_circuits_a", table_name="halls", postgresql_using="gin")
    op.drop_index("ix_halls_grid_height_m", table_name="halls")
    op.drop_index(
        "ix_halls_extras",
        table_name="halls",
        postgresql_using="gin",
        postgresql_ops={"extras": "jsonb_path_ops"},
    )
    op.drop_index("ix_halls_capacity_seated", table_name="halls")
    op.drop_table("halls")
    op.drop_index("uq_venues_city_name_street", table_name="venues")
    op.drop_index(
        "ix_venues_name_trgm",
        table_name="venues",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.drop_index("ix_venues_city_id_venue_type", table_name="venues")
    op.drop_table("venues")
    op.drop_index(op.f("ix_cities_district"), table_name="cities")
    op.drop_table("cities")
