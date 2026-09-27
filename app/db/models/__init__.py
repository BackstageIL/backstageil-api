"""ORM models. Every model module is imported here so Alembic sees all tables on Base.metadata."""

from app.db.models.city import City, District, LocalityType
from app.db.models.hall import Hall, PipeType, StageFloor
from app.db.models.hall_picture import HallPicture
from app.db.models.recommendation import Recommendation, RecommendationCategory
from app.db.models.venue import Venue, VenueType

__all__ = [
    "City",
    "District",
    "Hall",
    "HallPicture",
    "LocalityType",
    "PipeType",
    "Recommendation",
    "RecommendationCategory",
    "StageFloor",
    "Venue",
    "VenueType",
]
