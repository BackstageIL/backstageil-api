from typing import Any

import pytest

from app.db.models import District, LocalityType
from scripts.seed_cities import (
    F_CODE,
    F_DISTRICT,
    F_FORM,
    F_NAME_EN,
    F_NAME_HE,
    F_STATUS,
    F_TRANSLIT,
    CityRow,
    assign_slugs,
    classify,
    parse_record,
    select_rows,
)


def _record(
    code: int,
    name_en: str,
    *,
    status: int | None,
    form: int | None,
    district: int | None = 5,
    name_he: str = "שם",
    translit: str = "",
) -> dict[str, Any]:
    return {
        F_CODE: code,
        F_NAME_EN: name_en,
        F_NAME_HE: name_he,
        F_TRANSLIT: translit,
        F_DISTRICT: district,
        F_STATUS: status,
        F_FORM: form,
    }


@pytest.mark.parametrize(
    ("status", "form", "expected"),
    [
        (0, 130, LocalityType.CITY),  # Tel Aviv - Yafo
        (0, 250, LocalityType.CITY),  # Nazareth
        (99, 190, LocalityType.LOCAL_COUNCIL),  # Metula
        (6, 330, LocalityType.KIBBUTZ),  # Deganya Alef
        (50, 193, LocalityType.KIBBUTZ),  # Giv'at Brenner (large kibbutz)
        (50, 310, LocalityType.MOSHAV),
        (50, 320, LocalityType.MOSHAV),  # moshav shitufi
        (50, 191, LocalityType.MOSHAV),
        (50, 370, None),  # community settlement: not seeded by default
        (50, 450, None),  # small village: not seeded by default
        (None, None, None),
    ],
)
def test_classify(status: int | None, form: int | None, expected: LocalityType | None) -> None:
    assert classify(status, form) == expected


def test_parse_city_record() -> None:
    row = parse_record(_record(5000, "Tel Aviv - Yafo", status=0, form=130, district=5))

    assert row == CityRow(
        official_code=5000,
        name_en="Tel Aviv - Yafo",
        name_he="שם",
        district=District.TEL_AVIV,
        locality_type=LocalityType.CITY,
    )


def test_unselected_type_is_skipped_unless_code_requested() -> None:
    record = _record(1234, "Small Village", status=50, form=450)

    assert parse_record(record) is None
    extra = parse_record(record, frozenset({1234}))
    assert extra is not None
    assert extra.locality_type is LocalityType.OTHER


def test_english_name_falls_back_to_transliteration() -> None:
    row = parse_record(_record(7, "", status=0, form=160, translit="SHAHAR"))

    assert row is not None
    assert row.name_en == "Shahar"


def test_record_without_any_english_name_is_skipped() -> None:
    assert parse_record(_record(1722, "", status=99, form=None)) is None


def test_unknown_district_code_is_none() -> None:
    row = parse_record(_record(1, "Somewhere", status=0, form=160, district=None))

    assert row is not None
    assert row.district is None


def test_select_rows_reports_skipped_and_fails_on_unusable_requested_code(
    capsys: pytest.CaptureFixture[str],
) -> None:
    records = [
        _record(5000, "Tel Aviv - Yafo", status=0, form=130),
        _record(1722, "", status=99, form=None, name_he="מגדל תפן"),
    ]

    rows = select_rows(records, frozenset())
    assert [r.official_code for r in rows] == [5000]
    assert "Skipped 1722" in capsys.readouterr().out

    with pytest.raises(SystemExit, match=r"\[1722\]"):
        select_rows(records, frozenset({1722}))


def test_colliding_slugs_get_the_code_appended() -> None:
    rows = [
        CityRow(1, "Kinneret", "כנרת", None, LocalityType.KIBBUTZ),
        CityRow(2, "Kinneret", "כנרת", None, LocalityType.MOSHAV),
        CityRow(3, "Haifa", "חיפה", District.HAIFA, LocalityType.CITY),
    ]

    assert assign_slugs(rows) == {1: "kinneret-1", 2: "kinneret-2", 3: "haifa"}
