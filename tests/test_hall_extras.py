import pytest
from pydantic import ValidationError

from app.db.models import Hall
from app.schemas.hall_extras import (
    EXTRA_SPECS,
    FIELD_NOTE_KEYS,
    HallExtras,
    HallFieldNotes,
    ValueType,
)


def test_unregistered_extra_with_label_is_valid() -> None:
    extras = HallExtras.model_validate(
        {"stage_cameras": {"label": "Stage cameras", "note": "4 cameras on stage must be covered"}}
    )

    assert extras.root["stage_cameras"].label == "Stage cameras"
    assert extras.root["stage_cameras"].value is None


def test_registered_extra_needs_no_label_and_is_type_checked() -> None:
    extras = HallExtras.model_validate({"stage_shape": {"value": "Trapezoid front"}})
    assert extras.root["stage_shape"].label is None

    with pytest.raises(ValidationError, match="must be of type text"):
        HallExtras.model_validate({"stage_shape": {"value": True}})


def test_empty_extras_are_valid() -> None:
    assert HallExtras.model_validate({}).root == {}


def test_unregistered_extra_without_label_is_rejected() -> None:
    with pytest.raises(ValidationError, match="needs a label"):
        HallExtras.model_validate({"stage_cameras": {"note": "cover them"}})


def test_fixed_column_used_as_extra_is_rejected() -> None:
    with pytest.raises(ValidationError, match="fixed hall column"):
        HallExtras.model_validate({"has_green_room": {"value": True}})


def test_extra_key_must_be_snake_case() -> None:
    with pytest.raises(ValidationError, match="snake_case"):
        HallExtras.model_validate({"Stage Cameras": {"label": "Stage cameras", "value": True}})


def test_extra_without_value_or_note_is_rejected() -> None:
    with pytest.raises(ValidationError, match="needs a value, a note, or both"):
        HallExtras.model_validate({"stage_cameras": {"label": "Stage cameras"}})


def test_extra_fields_inside_an_extra_are_rejected() -> None:
    with pytest.raises(ValidationError):
        HallExtras.model_validate(
            {"stage_cameras": {"label": "Stage cameras", "value": True, "color": "red"}}
        )


def test_registry_entries_are_consistent() -> None:
    for key, spec in EXTRA_SPECS.items():
        assert key == key.lower().replace(" ", "_")
        assert spec.label
        assert spec.value_type in ValueType
        assert key not in Hall.__table__.columns


def test_field_notes_cover_the_technical_columns() -> None:
    assert {"proscenium_width_m", "has_green_room", "first_pipe_distance_m"} <= FIELD_NOTE_KEYS
    # free-text and bookkeeping columns don't get notes
    assert not {"notes", "known_issues", "house_pa", "source", "slug"} & FIELD_NOTE_KEYS
    assert set(Hall.__table__.columns.keys()) >= FIELD_NOTE_KEYS


def test_field_notes_only_for_fixed_columns() -> None:
    notes = HallFieldNotes.model_validate({"proscenium_width_m": "Adjustable, 12-16 m"})
    assert notes.root["proscenium_width_m"].startswith("Adjustable")

    with pytest.raises(ValidationError, match="no technical hall column"):
        HallFieldNotes.model_validate({"green_room": "huge"})
