"""
Load verified venue data (JSON list of {venue, hall} items) into the database.

Usage:
  uv run python -m scripts.load_venues PATH --dry-run      # validate only
  uv run python -m scripts.load_venues PATH                # upsert into DATABASE_URL (unpublished)
  uv run python -m scripts.load_venues PATH --publish      # upsert and mark as published

Idempotent: venues are matched by slug, halls by (venue, slug). Everything is written in one
transaction: if any item fails, nothing is written. The input file stays local (never committed).
"""

import argparse
import asyncio
import sys
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from app.core.config import get_settings
from app.core.exceptions import DomainException
from app.db.session import Database
from app.schemas.admin import ImportReport
from app.schemas.venue_import import VenueImportItem
from app.services.venue_import import duplicate_slugs, import_items

_ITEMS = TypeAdapter(list[VenueImportItem])


def load_items(path: Path) -> list[VenueImportItem]:
    """Parse and validate the whole file; raise SystemExit listing every problem."""
    try:
        items = _ITEMS.validate_json(path.read_bytes())
    except ValidationError as exc:
        problems = "\n".join(
            f"  item {'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        count = exc.error_count()
        raise SystemExit(f"{path.name}: {count} validation error(s)\n{problems}") from exc
    duplicates = duplicate_slugs(items)
    if duplicates:
        raise SystemExit(f"Duplicate venue slugs in {path.name}: {duplicates}")
    return items


async def _load(items: list[VenueImportItem], publish: bool) -> ImportReport:
    database_url = get_settings().database_url
    if database_url is None:
        raise SystemExit("DATABASE_URL is not set")
    database = Database(database_url.get_secret_value())
    try:
        async with database.sessionmaker() as session, session.begin():
            return await import_items(session, items, publish=publish)
    except DomainException as exc:
        raise SystemExit(f"Nothing written: {exc.message}") from exc
    finally:
        await database.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Load verified venue data")
    parser.add_argument("path", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="validate only, write nothing")
    parser.add_argument("--publish", action="store_true", help="mark venues and halls as published")
    args = parser.parse_args(argv)

    items = load_items(args.path)
    print(f"{len(items)} items valid")
    if args.dry_run:
        return
    report = asyncio.run(_load(items, args.publish))
    print(
        f"Venues: {report.venues_created} created, {report.venues_updated} updated | "
        f"Halls: {report.halls_created} created, {report.halls_updated} updated"
    )


if __name__ == "__main__":
    main(sys.argv[1:])
