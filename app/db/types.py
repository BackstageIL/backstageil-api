"""Reusable column types."""

from enum import StrEnum

from sqlalchemy import Enum


def str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """Store a StrEnum as VARCHAR + CHECK constraint (by value, e.g. 'culture_hall').

    Non-native enums are easier to evolve than PostgreSQL ENUM types: adding a value only
    changes a CHECK constraint in a migration.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
        length=max(len(member.value) for member in enum_cls),
    )
