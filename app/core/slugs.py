import re
import unicodedata


def slugify(*parts: str) -> str:
    """Build a URL slug from English parts: slugify("Zappa", "Herzliya") -> "zappa-herzliya"."""
    text = " ".join(parts)
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    if not slug:
        raise ValueError(f"Cannot build a slug from {parts!r}")
    return slug
