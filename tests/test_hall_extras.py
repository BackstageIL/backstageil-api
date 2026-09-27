import pytest
from pydantic import ValidationError

from app.schemas.hall_extras import (
    EXTRA_SPECS,
    FIELD_NOTE_KEYS,
    HallExtras,
    HallFieldNotes,
    ValueType,
)


def test_valid_extras_with_value_and_optional_note() -> None:
    extras = HallExtras.model_validate(
        {
            "green_room": {"value": True, "note": "huge"},
            "showers": {"value": True},
            "sightline_issues": {"value": "high stage, rows 1-2 can't see feet"},
        }
    )

    assert extras.root["green_room"].note == "huge"
    assert extras.root["showers"].note is None


def test_note_only_extra_is_allowed() -> None:
    extras = HallExtras.model_validate({"truss_hanging": {"note": "ask the venue first"}})

    assert extras.root["truss_hanging"].value is None


def test_empty_extras_are_valid() -> None:
    assert HallExtras.model_validate({}).root == {}


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown extra 'greenroom'"):
        HallExtras.model_validate({"greenroom": {"value": True}})


def test_wrong_value_type_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must be of type bool"):
        HallExtras.model_validate({"green_room": {"value": "yes"}})


def test_text_extra_rejects_bool() -> None:
    with pytest.raises(ValidationError, match="must be of type text"):
        HallExtras.model_validate({"sightline_issues": {"value": True}})


def test_extra_without_value_or_note_is_rejected() -> None:
    with pytest.raises(ValidationError, match="needs a value, a note, or both"):
        HallExtras.model_validate({"green_room": {}})


def test_extra_fields_inside_an_extra_are_rejected() -> None:
    with pytest.raises(ValidationError):
        HallExtras.model_validate({"green_room": {"value": True, "color": "green"}})


def test_registry_entries_are_consistent() -> None:
    for key, spec in EXTRA_SPECS.items():
        assert key == key.lower().replace(" ", "_")
        assert spec.label
        assert spec.value_type in ValueType
    # extras and fixed columns never share a name
    assert not set(EXTRA_SPECS) & FIELD_NOTE_KEYS


def test_field_notes_only_for_fixed_columns() -> None:
    notes = HallFieldNotes.model_validate({"proscenium_width_m": "12-16 m, adjustable"})
    assert notes.root["proscenium_width_m"].startswith("12")

    with pytest.raises(ValidationError, match="no fixed hall column"):
        HallFieldNotes.model_validate({"green_room": "huge"})
