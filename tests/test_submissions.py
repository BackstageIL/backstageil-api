"""Submission helpers (BSIL-58): anonymous connection codes, file names and file checks."""

from datetime import date
from io import BytesIO

import pytest
from PIL import Image, TiffImagePlugin

from app.core.exceptions import InvalidSubmissionFileError
from app.services import submissions
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


def image_bytes(image_format: str, size: tuple[int, int] = (10, 10)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", size, "red").save(buffer, image_format)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("image_format", "content_type", "name"),
    [
        ("JPEG", "image/jpeg", "photo.jpg"),
        ("PNG", "image/png", "photo.png"),
        ("WEBP", "image/webp", "photo.webp"),
    ],
)
def test_allowed_images_are_kept(image_format: str, content_type: str, name: str) -> None:
    checked = check_file("photo.bin", image_bytes(image_format), 0)

    assert checked.content_type == content_type
    assert checked.name == name


@pytest.mark.parametrize("image_format", ["TIFF", "BMP", "GIF"])
def test_other_image_formats_are_refused(image_format: str) -> None:
    with pytest.raises(InvalidSubmissionFileError):
        check_file("photo.jpg", image_bytes(image_format), 0)


def test_the_parser_of_another_format_never_sees_the_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_self: object) -> None:
        raise AssertionError("the TIFF parser was run")

    data = image_bytes("TIFF")
    monkeypatch.setattr(TiffImagePlugin.TiffImageFile, "_open", fail)

    with pytest.raises(InvalidSubmissionFileError):
        check_file("photo.tiff", data, 0)


def test_corrupt_image_is_refused() -> None:
    with pytest.raises(InvalidSubmissionFileError):
        check_file("photo.jpg", image_bytes("JPEG")[:40], 0)


def test_image_with_too_many_pixels_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(submissions, "MAX_PIXELS", 50)

    with pytest.raises(InvalidSubmissionFileError):
        check_file("photo.png", image_bytes("PNG"), 0)


def test_decompression_bomb_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)  # Pillow refuses at twice this many

    with pytest.raises(InvalidSubmissionFileError):
        check_file("photo.png", image_bytes("PNG"), 0)
