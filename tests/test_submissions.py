"""Submission helpers (BSIL-58): anonymous connection codes, file names and file checks."""

from datetime import date

import pytest

from app.core.exceptions import InvalidSubmissionFileError
from app.services.submissions import check_file, client_hash, safe_name


def test_connection_codes_are_stable_within_a_day_and_change_daily() -> None:
    day = date(2026, 10, 14)
    code = client_hash("secret", "203.0.113.7", day)

    assert code == client_hash("secret", "203.0.113.7", day)
    assert code != client_hash("secret", "203.0.113.7", date(2026, 10, 15))
    assert code != client_hash("other-secret", "203.0.113.7", day)
    assert "203.0.113.7" not in code and len(code) == 64


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\dana\\rider.pdf", "rider.pdf"),
        ("תוכנית צוגים.pdf", "תוכנית צוגים.pdf"),
        ("a<b>c?.pdf", "a_b_c_.pdf"),
        ("", "file-1"),
        ("...", "file-1"),
    ],
)
def test_file_names_lose_folders_and_odd_characters(name: str, expected: str) -> None:
    assert safe_name(name, "file-1") == expected


@pytest.mark.parametrize(
    ("name", "content_type"),
    [("old.doc", "application/msword"), ("old.xls", "application/vnd.ms-excel")],
)
def test_old_office_files_are_accepted_by_content(name: str, content_type: str) -> None:
    ole = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 16

    assert check_file(name, ole, 0).content_type == content_type


def test_office_extension_with_other_content_is_rejected() -> None:
    with pytest.raises(InvalidSubmissionFileError):
        check_file("sheet.xlsx", b"%!PS-Adobe", 0)
