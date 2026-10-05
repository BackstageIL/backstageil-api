"""Picture processing: formats, metadata stripping, orientation and sizes."""

from io import BytesIO

import pytest
from PIL import Image

from app.core.exceptions import InvalidPictureError
from app.services import picture_processing
from app.services.picture_processing import file_keys, process_picture

GPS_IFD = 0x8825
ORIENTATION = 0x0112


def encode(image: Image.Image, image_format: str, **params: object) -> bytes:
    buffer = BytesIO()
    image.save(buffer, image_format, **params)
    return buffer.getvalue()


def decode(data: bytes) -> Image.Image:
    image = Image.open(BytesIO(data))
    image.load()
    return image


def photo_with_gps(size: tuple[int, int] = (3000, 2000), orientation: int = 1) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "Test camera maker"
    exif[ORIENTATION] = orientation
    exif.get_ifd(GPS_IFD).update({1: "N", 2: (32.0, 4.0, 0.0), 3: "E", 4: (34.0, 46.0, 0.0)})
    return encode(Image.new("RGB", size, "red"), "JPEG", exif=exif)


def test_jpeg_becomes_webp_large_and_thumb_without_metadata() -> None:
    result = process_picture(photo_with_gps())

    assert set(result.files) == {"large", "thumb"}
    large, thumb = decode(result.files["large"]), decode(result.files["thumb"])
    assert (large.format, thumb.format) == ("WEBP", "WEBP")
    assert large.size == (1600, 1067) == (result.width, result.height)
    assert thumb.size == (400, 267)
    for image in (large, thumb):
        assert "exif" not in image.info
        assert "xmp" not in image.info
        assert not image.getexif()


def test_orientation_is_applied_then_dropped() -> None:
    # Orientation 6 = the camera was turned: the stored landscape pixels display as portrait
    result = process_picture(photo_with_gps(size=(1200, 800), orientation=6))

    assert (result.width, result.height) == (800, 1200)
    assert not decode(result.files["large"]).getexif()


def test_small_images_are_not_upscaled() -> None:
    result = process_picture(encode(Image.new("RGB", (300, 200)), "PNG"))

    assert (result.width, result.height) == (300, 200)
    assert decode(result.files["thumb"]).size == (300, 200)


def test_png_transparency_is_kept() -> None:
    result = process_picture(encode(Image.new("RGBA", (50, 50), (0, 0, 0, 0)), "PNG"))

    assert decode(result.files["large"]).mode == "RGBA"


def test_rgb_color_profile_is_kept_cmyk_profile_is_not() -> None:
    profile = b"fake-icc-profile"
    rgb = process_picture(encode(Image.new("RGB", (40, 40)), "JPEG", icc_profile=profile))
    cmyk = process_picture(encode(Image.new("CMYK", (40, 40)), "JPEG", icc_profile=profile))

    assert decode(rgb.files["large"]).info.get("icc_profile") == profile
    assert decode(cmyk.files["large"]).mode == "RGB"
    assert not decode(cmyk.files["large"]).info.get("icc_profile")


def test_same_file_same_hash_different_file_different_hash() -> None:
    first = encode(Image.new("RGB", (10, 10), "red"), "PNG")
    second = encode(Image.new("RGB", (10, 10), "blue"), "PNG")

    assert process_picture(first).content_hash == process_picture(first).content_hash
    assert process_picture(first).content_hash != process_picture(second).content_hash
    assert len(process_picture(first).content_hash) == 32


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not an image at all",
        encode(Image.new("RGB", (10, 10)), "GIF"),
        encode(Image.new("RGB", (10, 10)), "BMP"),
        encode(Image.new("RGB", (10, 10)), "JPEG")[:100],  # truncated
    ],
)
def test_unreadable_or_unsupported_files_are_rejected(data: bytes) -> None:
    with pytest.raises(InvalidPictureError):
        process_picture(data)


def test_too_many_pixels_is_rejected_before_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picture_processing, "MAX_PIXELS", 99)

    with pytest.raises(InvalidPictureError, match="too large"):
        process_picture(encode(Image.new("RGB", (10, 10)), "PNG"))


def test_file_keys() -> None:
    assert file_keys("pictures/abc") == ["pictures/abc/large.webp", "pictures/abc/thumb.webp"]
