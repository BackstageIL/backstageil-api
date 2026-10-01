import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.venue_import import VenueImportItem, check_no_contact_details
from scripts.load_venues import load_items


def item(**hall_overrides: Any) -> dict[str, Any]:
    return {
        "sheet": "תל אביב",
        "venue": {
            "slug": "test-venue",
            "name": "Test Venue",
            "city_code": 5000,
            "street_address": "1 Test St",
            "venue_type": "culture_hall",
            "website": "https://example.com/",
        },
        "hall": {
            "slug": "main",
            "name": "Main hall",
            "stage_width_m": 7.5,
            "power_circuits_a": [32, 63],
            "has_green_room": True,
            "extras": {"stage_cameras": {"label": "Stage cameras", "note": "Cover them"}},
            "field_notes": {"power_circuits_a": "2\u00d763 A, 1\u00d7125 A"},
        }
        | hall_overrides,
    }


def test_valid_item_and_database_values() -> None:
    parsed = VenueImportItem.model_validate(item())

    values = parsed.hall_values()
    assert values["stage_width_m"] == Decimal("7.5")
    assert values["has_green_room"] is True
    assert values["extras"] == {"stage_cameras": {"label": "Stage cameras", "note": "Cover them"}}
    assert values["field_notes"] == {"power_circuits_a": "2\u00d763 A, 1\u00d7125 A"}


@pytest.mark.parametrize(
    "text",
    [
        "call 052-1234567",
        "call 0521234567",
        "+972 52 123 4567",
        "write to someone@venue.co.il",
    ],
)
def test_contact_details_are_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="phone number or email"):
        check_no_contact_details(text)


@pytest.mark.parametrize(
    "text",
    [
        "2\u00d763 A, 1\u00d7125 A, 4\u00d732 A",
        "rows 3-18 and 24",
        "seats 1-3 and 27-29",
        "12-16 m",
    ],
)
def test_technical_text_is_allowed(text: str) -> None:
    assert check_no_contact_details(text) == text


@pytest.mark.parametrize(
    "overrides",
    [
        {"notes": "ask Moshe 050-1234567"},
        {"extras": {"stage_cameras": {"label": "Cameras", "note": "boss@venue.com"}}},
        {"extras": {"stage_cameras": {"label": "Call 0541234567", "value": True}}},
        {"seat_kills": "ask Avi 052-7654321"},
        {"field_notes": {"stage_width_m": "call 0541234567"}},
    ],
)
def test_contact_details_hidden_in_hall_text_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="phone number or email"):
        VenueImportItem.model_validate(item(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"slug": "Main Hall"},  # not a slug
        {"capacity_seated": -1},
        {"stage_width_m": 0},
        {"power_circuits_a": [0]},
        {"extras": {"stage_cameras": {"value": True}}},  # unregistered extra without label
        {"extras": {"has_green_room": {"value": True}}},  # fixed column used as extra
        {"follow_spot_positions": -1},
        {"first_pipe_distance_m": -0.5},
        {"unknown_column": 1},  # typo in a field name
    ],
)
def test_invalid_hall_data_is_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        VenueImportItem.model_validate(item(**overrides))


def test_load_items_reports_all_problems_and_duplicates(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([item(capacity_seated=-1), item(slug="Bad Slug")]))
    with pytest.raises(SystemExit, match="2 validation error"):
        load_items(bad)

    duplicated = tmp_path / "dup.json"
    duplicated.write_text(json.dumps([item(), item()]))
    with pytest.raises(SystemExit, match="Duplicate venue slugs"):
        load_items(duplicated)

    good = tmp_path / "good.json"
    good.write_text(json.dumps([item()]))
    assert len(load_items(good)) == 1


def test_import_schema_covers_every_hall_column() -> None:
    """A new hall column must also be importable (and vice versa)."""
    from app.db.models import Hall
    from app.schemas.venue_import import HallImport

    bookkeeping = {
        "id",
        "venue_id",
        "extras",
        "field_notes",
        "is_published",
        "created_at",
        "updated_at",
    }
    model_columns = set(Hall.__table__.columns.keys()) - bookkeeping
    schema_fields = set(HallImport.model_fields) - {"extras", "field_notes"}

    assert model_columns == schema_fields
