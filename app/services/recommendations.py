"""
Venue recommendations: places near a venue that crews need (food, parking, hotel...).

Sponsored places are listed first while their sponsorship runs: `is_sponsored` is set and
`sponsored_until` (the last day, Israel time) is empty or not yet past. Expiry is decided when
the list is read, so nothing has to run on a schedule.
"""

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import RecommendationNotFoundError
from app.db.models import Recommendation, RecommendationCategory
from app.schemas.recommendations import (
    AdminRecommendation,
    RecommendationCreate,
    RecommendationPatch,
)
from app.schemas.recommendations import Recommendation as PublicRecommendation
from app.services.venues import find_venue

ISRAEL = ZoneInfo("Asia/Jerusalem")


def israel_today() -> date:
    """Route dependency (tests override it): today's date in Israel."""
    return datetime.now(ISRAEL).date()


def _sponsored_now(today: date) -> ColumnElement[bool]:
    return and_(
        Recommendation.is_sponsored,
        or_(Recommendation.sponsored_until.is_(None), Recommendation.sponsored_until >= today),
    )


def is_sponsored_now(recommendation: Recommendation, today: date) -> bool:
    until = recommendation.sponsored_until
    return recommendation.is_sponsored and (until is None or until >= today)


async def list_recommendations(
    session: AsyncSession,
    venue_slug: str,
    *,
    today: date,
    category: RecommendationCategory | None = None,
    public: bool = True,
) -> list[Recommendation]:
    """Public: published venue, active rows only. Admin (public=False): everything."""
    venue = await find_venue(session, venue_slug, published_only=public)
    query = select(Recommendation).where(Recommendation.venue_id == venue.id)
    if public:
        query = query.where(Recommendation.is_active)
    if category is not None:
        query = query.where(Recommendation.category == category)
    query = query.order_by(
        _sponsored_now(today).desc(),
        Recommendation.display_order,
        Recommendation.name,
        Recommendation.id,
    )
    return list(await session.scalars(query))


def public_view(recommendation: Recommendation, today: date) -> PublicRecommendation:
    return PublicRecommendation(
        id=recommendation.id,
        category=recommendation.category,
        name=recommendation.name,
        address=recommendation.address,
        website=recommendation.website,
        phone=recommendation.phone,
        note=recommendation.note,
        distance_m=recommendation.distance_m,
        is_sponsored=is_sponsored_now(recommendation, today),
    )


def admin_view(recommendation: Recommendation, today: date) -> AdminRecommendation:
    values = {
        name: getattr(recommendation, name)
        for name in AdminRecommendation.model_fields
        if name != "sponsored_now"
    }
    values["sponsored_now"] = is_sponsored_now(recommendation, today)
    return AdminRecommendation.model_validate(values)


def _column_values(fields: dict[str, Any], website: object) -> dict[str, Any]:
    if "website" in fields:
        fields["website"] = str(website) if website else None
    return fields


async def create_recommendation(
    session: AsyncSession, venue_slug: str, data: RecommendationCreate
) -> Recommendation:
    venue = await find_venue(session, venue_slug, published_only=False)
    recommendation = Recommendation(
        venue_id=venue.id, **_column_values(data.model_dump(), data.website)
    )
    session.add(recommendation)
    await session.flush()
    await session.refresh(recommendation)  # server-side timestamps
    return recommendation


async def find_recommendation(
    session: AsyncSession, venue_slug: str, recommendation_id: int
) -> Recommendation:
    venue = await find_venue(session, venue_slug, published_only=False)
    recommendation = await session.scalar(
        select(Recommendation).where(
            Recommendation.id == recommendation_id, Recommendation.venue_id == venue.id
        )
    )
    if recommendation is None:
        raise RecommendationNotFoundError(recommendation_id)
    return recommendation


async def patch_recommendation(
    session: AsyncSession, venue_slug: str, recommendation_id: int, patch: RecommendationPatch
) -> Recommendation:
    recommendation = await find_recommendation(session, venue_slug, recommendation_id)
    changes = _column_values(patch.model_dump(exclude_unset=True), patch.website)
    for field, value in changes.items():
        setattr(recommendation, field, value)
    await session.flush()
    await session.refresh(recommendation)  # server-side updated_at
    return recommendation


async def delete_recommendation(
    session: AsyncSession, venue_slug: str, recommendation_id: int
) -> None:
    recommendation = await find_recommendation(session, venue_slug, recommendation_id)
    await session.delete(recommendation)
    await session.flush()
