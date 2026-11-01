"""The site snapshot: all published data in one response, in the shapes of the public endpoints."""

from pydantic import BaseModel

from app.schemas.pictures import Picture
from app.schemas.recommendations import Recommendation
from app.schemas.venues import HallDocument, VenueDetail, VenueSummary


class SiteHall(BaseModel):
    document: HallDocument
    pictures: list[Picture]


class SiteVenue(BaseModel):
    summary: VenueSummary
    detail: VenueDetail
    pictures: list[Picture]
    recommendations: list[Recommendation]
    halls: list[SiteHall]  # same order as detail.halls


class SiteSnapshot(BaseModel):
    venues: list[SiteVenue]  # same order as the public venue list
