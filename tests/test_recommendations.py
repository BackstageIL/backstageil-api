"""Recommendation helpers that need no database."""

from datetime import UTC, date, datetime, tzinfo

import pytest

from app.services import recommendations
from app.services.recommendations import ISRAEL, israel_today


def test_today_is_the_israel_date(monkeypatch: pytest.MonkeyPatch) -> None:
    # 22:30 UTC on Oct 15 is already Oct 16 in Israel (UTC+3 in summer time)
    instant = datetime(2026, 10, 15, 22, 30, tzinfo=UTC)

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
            return instant.astimezone(tz)

    monkeypatch.setattr(recommendations, "datetime", FixedClock)

    assert israel_today() == date(2026, 10, 16)


def test_israel_time_zone_is_available() -> None:
    # Comes from the tzdata package where the system has no time zone database (slim images)
    assert datetime(2026, 7, 1, 12, tzinfo=ISRAEL).utcoffset() is not None
