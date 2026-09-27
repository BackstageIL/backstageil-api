import pytest

from app.core.slugs import slugify


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("Zappa", "Herzliya"), "zappa-herzliya"),
        (("Heichal HaTarbut", "Tel Aviv-Yafo"), "heichal-hatarbut-tel-aviv-yafo"),
        (("Be'er Sheva",), "be-er-sheva"),
        (("  Main   Hall  ",), "main-hall"),
        (("Café Élite",), "cafe-elite"),
    ],
)
def test_slugify(parts: tuple[str, ...], expected: str) -> None:
    assert slugify(*parts) == expected


def test_slugify_rejects_input_without_ascii_letters_or_digits() -> None:
    with pytest.raises(ValueError, match="Cannot build a slug"):
        slugify("היכל התרבות")
