"""
Seed the `cities` table from the official CBS localities file (data.gov.il, open data).

Kept, by municipal status / locality form only:
  - cities (municipal status 0) and local councils (status 99)
  - kibbutzim (form 330, 193) and moshavim (form 310, 320, 191, 192)
Any other locality can be added explicitly with --code (e.g. where a venue is).

Usage:
  uv run python -m scripts.seed_cities --dry-run
  uv run python -m scripts.seed_cities                 # upsert into DATABASE_URL
  uv run python -m scripts.seed_cities --code 1234     # also add locality 1234

Idempotent: rows are upserted by official_code. The downloaded data is never stored in the repo.
Source: CBS "יישובים בישראל - קובצי יישובים" (dataset localities-in-israel), 2023 file.
"""

import argparse
import asyncio
import json
import sys
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.slugs import slugify
from app.db.models import City, District, LocalityType
from app.db.session import Database

DATASTORE_URL = "https://data.gov.il/api/3/action/datastore_search"
CBS_LOCALITIES_2023 = "d47a54ff-87f0-44b3-b33a-f284c0c38e5a"
PAGE_SIZE = 500

# CBS field names (Hebrew, as published)
F_CODE = "סמל יישוב"
F_NAME_HE = "שם יישוב"
F_NAME_EN = "שם יישוב באנגלית"
F_TRANSLIT = "תעתיק"
F_DISTRICT = "סמל מחוז"
F_STATUS = "סמל מעמד מונציפאלי"
F_FORM = "צורת יישוב שוטפת - ארעי"

STATUS_CITY = 0
STATUS_LOCAL_COUNCIL = 99
KIBBUTZ_FORMS = frozenset({330, 193})
MOSHAV_FORMS = frozenset({310, 320, 191, 192})

# English names for localities the CBS file publishes without one (added with --code for a venue)
ENGLISH_NAMES: dict[int, str] = {
    1711: "Mif'alei Tzemach",  # מפעלי צמח, Tzemach junction (Beit Gabriel)
}

DISTRICTS: dict[int, District] = {
    1: District.JERUSALEM,
    2: District.NORTH,
    3: District.HAIFA,
    4: District.CENTER,
    5: District.TEL_AVIV,
    6: District.SOUTH,
    7: District.JUDEA_SAMARIA,
}


@dataclass(frozen=True)
class CityRow:
    official_code: int
    name_en: str
    name_he: str
    district: District | None
    locality_type: LocalityType


def classify(status: int | None, form: int | None) -> LocalityType | None:
    """Locality type from CBS municipal status and form; None = not seeded by default."""
    if status == STATUS_CITY:
        return LocalityType.CITY
    if status == STATUS_LOCAL_COUNCIL:
        return LocalityType.LOCAL_COUNCIL
    if form in KIBBUTZ_FORMS:
        return LocalityType.KIBBUTZ
    if form in MOSHAV_FORMS:
        return LocalityType.MOSHAV
    return None


def _english_name(record: dict[str, Any]) -> str:
    name = (record.get(F_NAME_EN) or "").strip()
    if name:
        return " ".join(name.split())
    translit = (record.get(F_TRANSLIT) or "").strip().title()
    return translit or ENGLISH_NAMES.get(int(record[F_CODE]), "")


def parse_record(
    record: dict[str, Any], extra_codes: frozenset[int] = frozenset()
) -> CityRow | None:
    """Map one CBS record to a CityRow, or None if it is not selected."""
    code = int(record[F_CODE])
    locality_type = classify(record.get(F_STATUS), record.get(F_FORM))
    if locality_type is None:
        if code not in extra_codes:
            return None
        locality_type = LocalityType.OTHER

    name_en = _english_name(record)
    name_he = (record.get(F_NAME_HE) or "").strip()
    if not name_en or not name_he:
        return None
    district_code = record.get(F_DISTRICT)
    return CityRow(
        official_code=code,
        name_en=name_en,
        name_he=name_he,
        district=DISTRICTS.get(int(district_code)) if district_code is not None else None,
        locality_type=locality_type,
    )


def assign_slugs(rows: Iterable[CityRow]) -> dict[int, str]:
    """Slug per official code; names that collide get the official code appended."""
    rows = list(rows)
    base = {row.official_code: slugify(row.name_en) for row in rows}
    counts = Counter(base.values())
    return {code: slug if counts[slug] == 1 else f"{slug}-{code}" for code, slug in base.items()}


def fetch_records(resource_id: str = CBS_LOCALITIES_2023) -> list[dict[str, Any]]:
    """Download all records of a data.gov.il datastore resource (paged)."""
    records: list[dict[str, Any]] = []
    offset = 0
    while True:
        query = urllib.parse.urlencode(
            {"resource_id": resource_id, "limit": PAGE_SIZE, "offset": offset}
        )
        with urllib.request.urlopen(f"{DATASTORE_URL}?{query}", timeout=60) as response:
            result = json.load(response)["result"]
        page = result["records"]
        records.extend(page)
        offset += len(page)
        if not page or offset >= result["total"]:
            return records


async def upsert_cities(session: AsyncSession, rows: list[CityRow]) -> int:
    """Insert or update cities by official_code. Returns the number of rows written."""
    if not rows:
        return 0
    slugs = assign_slugs(rows)
    values = [
        {
            "official_code": row.official_code,
            "name_en": row.name_en,
            "name_he": row.name_he,
            "slug": slugs[row.official_code],
            "district": row.district,
            "locality_type": row.locality_type,
        }
        for row in rows
    ]
    statement = insert(City).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=[City.official_code],
        set_={
            "name_en": statement.excluded.name_en,
            "name_he": statement.excluded.name_he,
            "slug": statement.excluded.slug,
            "district": statement.excluded.district,
            "locality_type": statement.excluded.locality_type,
        },
    )
    await session.execute(statement)
    return len(values)


def select_rows(records: list[dict[str, Any]], extra_codes: frozenset[int]) -> list[CityRow]:
    rows: list[CityRow] = []
    for record in records:
        row = parse_record(record, extra_codes)
        if row is not None:
            rows.append(row)
            continue
        wanted = int(record[F_CODE]) in extra_codes or classify(
            record.get(F_STATUS), record.get(F_FORM)
        )
        if wanted:  # selected by type/code but unusable: say so instead of dropping silently
            print(f"Skipped {record[F_CODE]} ({record.get(F_NAME_HE)}): no English name in source")
    missing = extra_codes - {row.official_code for row in rows}
    if missing:
        raise SystemExit(f"Locality codes not usable from the source: {sorted(missing)}")
    return rows


async def _seed(rows: list[CityRow]) -> None:
    database_url = get_settings().database_url
    if database_url is None:
        raise SystemExit("DATABASE_URL is not set")
    database = Database(database_url.get_secret_value())
    try:
        async with database.sessionmaker() as session, session.begin():
            written = await upsert_cities(session, rows)
        print(f"Upserted {written} cities")
    finally:
        await database.dispose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else None)
    parser.add_argument("--dry-run", action="store_true", help="print a summary, write nothing")
    parser.add_argument(
        "--code", type=int, action="append", default=[], help="also add this locality code"
    )
    parser.add_argument("--resource-id", default=CBS_LOCALITIES_2023)
    args = parser.parse_args(argv)

    rows = select_rows(fetch_records(args.resource_id), frozenset(args.code))
    print(f"Selected {len(rows)} localities")
    for locality_type, count in sorted(Counter(r.locality_type for r in rows).items()):
        print(f"  {locality_type}: {count}")
    if args.dry_run:
        return
    asyncio.run(_seed(rows))


if __name__ == "__main__":
    main(sys.argv[1:])
