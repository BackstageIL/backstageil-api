"""ORM models. Every model module is imported here so Alembic sees all tables on Base.metadata."""

from app.db.models.city import City, District, LocalityType
from app.db.models.hall import Hall, PipeType, StageFloor
from app.db.models.hall_picture import HallPicture
from app.db.models.recommendation import Recommendation, RecommendationCategory
from app.db.models.submission import Submission, SubmissionKind, SubmissionStatus
from app.db.models.vendor import Vendor, VendorCategory
from app.db.models.vendor_picture import VendorPicture
from app.db.models.venue import Venue, VenueType
from app.db.models.venue_picture import VenuePicture

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
    "Submission",
    "SubmissionKind",
    "SubmissionStatus",
    "Vendor",
    "VendorCategory",
    "VendorPicture",
    "Venue",
    "VenuePicture",
    "VenueType",
]
