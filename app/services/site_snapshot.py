"""
All published data in one response, so a website build makes one API call instead of one per
venue, hall, picture list and recommendation list (BSIL-74, Vercel's free plan limits CPU time).

A fixed number of queries, whatever the number of venues; rows are grouped here in Python. Each
part must equal what the matching public endpoint returns, so the same builders are used.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Hall, HallPicture, Venue, VenuePicture
from app.schemas.pictures import Picture
from app.schemas.site import SiteHall, SiteSnapshot, SiteVenue
from app.schemas.venues import CityRef, HallDocument, VenueDetail, VenueSummary
from app.services import recommendations
from app.services.pictures import to_model
from app.services.venues import (
    build_hall_document,
    published_venues,
    venue_detail,
    venue_ref,
    venue_summary,
)


def _group_by[T](rows: Iterable[T], key: Callable[[T], int]) -> defaultdict[int, list[T]]:
    groups: defaultdict[int, list[T]] = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    return groups


async def site_snapshot(
    session: AsyncSession, *, base_url: str | None, today: date
) -> SiteSnapshot:
    venue_rows = await published_venues(session)
    halls = _group_by(
        await session.scalars(
            select(Hall)
            .join(Venue, Venue.id == Hall.venue_id)
            .where(Venue.is_published, Hall.is_published)
            .order_by(Hall.name)
        ),
        lambda hall: hall.venue_id,
    )
    # The next three also read rows of unpublished venues and halls: they are looked up below by
    # published ids only, so they never reach the response.
    hall_pictures = _group_by(
        await session.scalars(
            select(HallPicture).order_by(HallPicture.display_order, HallPicture.id)
        ),
        lambda picture: picture.hall_id,
    )
    venue_pictures = _group_by(
        await session.scalars(
            select(VenuePicture).order_by(VenuePicture.display_order, VenuePicture.id)
        ),
        lambda picture: picture.venue_id,
    )
    places = _group_by(
        await recommendations.active_recommendations(session, today=today),
        lambda place: place.venue_id,
    )

    venues = []
    for venue, city, count in venue_rows:
        city_ref = CityRef.model_validate(city)
        ref = venue_ref(venue, city_ref)
        venues.append(
            SiteVenue(
                summary=venue_summary(venue, city, count, model=VenueSummary),
                detail=venue_detail(venue, city_ref, halls[venue.id], model=VenueDetail),
                pictures=[to_model(row, base_url, Picture) for row in venue_pictures[venue.id]],
                recommendations=[
                    recommendations.public_view(row, today) for row in places[venue.id]
                ],
                halls=[
                    SiteHall(
                        document=build_hall_document(hall, ref, model=HallDocument),
                        pictures=[
                            to_model(row, base_url, Picture) for row in hall_pictures[hall.id]
                        ],
                    )
                    for hall in halls[venue.id]
                ],
            )
        )
    return SiteSnapshot(venues=venues)
