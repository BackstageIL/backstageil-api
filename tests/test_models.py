import pytest
from sqlalchemy.orm import configure_mappers

from app.db.models import City, Hall, HallPicture, Recommendation, Venue


@pytest.mark.parametrize(
    ("attribute", "target"),
    [
        (City.venues, Venue),
        (Venue.city, City),
        (Venue.halls, Hall),
        (Venue.recommendations, Recommendation),
        (Hall.venue, Venue),
        (Hall.pictures, HallPicture),
        (HallPicture.hall, Hall),
        (Recommendation.venue, Venue),
    ],
)
def test_relationships_resolve_to_the_right_model(attribute: object, target: type) -> None:
    """Relationship annotations are forward references (lazily evaluated since Python 3.14);
    this fails if SQLAlchemy can no longer resolve them."""
    configure_mappers()

    assert attribute.property.mapper.class_ is target  # type: ignore[attr-defined]
