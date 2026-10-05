"""
Turn an uploaded image into the files that are served: WebP in a few sizes, no metadata.

The image is decoded (the declared content type is never trusted), turned upright according to
its EXIF orientation and re-encoded. Re-encoding drops EXIF/XMP, so camera details and GPS
location never reach the bucket; only the color profile is kept so colors stay right.
"""

import hashlib
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.exceptions import InvalidPictureError

ALLOWED_FORMATS = frozenset({"JPEG", "PNG", "WEBP"})
MAX_PIXELS = 50_000_000  # 50 MP: larger than any phone photo, small enough to decode safely
# Longest edge in pixels per served size (never upscaled)
SIZES = {"large": 1600, "thumb": 400}
WEBP_QUALITY = 80


@dataclass(frozen=True)
class ProcessedPicture:
    content_hash: str  # of the uploaded bytes: the same file always gets the same key
    width: int  # of the large size
    height: int
    files: dict[str, bytes]  # size name -> WebP bytes


def file_key(storage_key: str, size: str) -> str:
    return f"{storage_key}/{size}.webp"


def file_keys(storage_key: str) -> list[str]:
    return [file_key(storage_key, size) for size in SIZES]


def process_picture(data: bytes) -> ProcessedPicture:
    """CPU-bound: run it in a worker thread."""
    image = _open(data)
    # A CMYK or grayscale profile would be wrong on the RGB output: keep only RGB profiles.
    icc_profile = image.info.get("icc_profile") if image.mode in ("RGB", "RGBA") else None
    image = ImageOps.exif_transpose(image)
    image = image.convert("RGBA" if image.has_transparency_data else "RGB")

    files: dict[str, bytes] = {}
    width = height = 0
    for size, longest_edge in SIZES.items():
        resized = image.copy()
        resized.thumbnail((longest_edge, longest_edge), Image.Resampling.LANCZOS)
        if size == "large":
            width, height = resized.size
        buffer = BytesIO()
        resized.save(buffer, "WEBP", quality=WEBP_QUALITY, icc_profile=icc_profile)
        files[size] = buffer.getvalue()

    return ProcessedPicture(
        content_hash=hashlib.sha256(data).hexdigest()[:32],
        width=width,
        height=height,
        files=files,
    )


def _open(data: bytes) -> Image.Image:
    try:
        image = Image.open(BytesIO(data))  # reads the header only
        if image.format not in ALLOWED_FORMATS:
            raise InvalidPictureError(
                f"Unsupported image format {image.format}; use JPEG, PNG or WebP",
                details={"format": image.format},
            )
        if image.width * image.height > MAX_PIXELS:
            raise InvalidPictureError(
                f"The image is too large ({image.width}x{image.height} pixels)",
                details={"width": image.width, "height": image.height},
            )
        image.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise InvalidPictureError("The file is not a readable JPEG, PNG or WebP image") from exc
    return image
