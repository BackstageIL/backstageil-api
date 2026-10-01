"""HTTP cache headers for public, read-only endpoints."""

from fastapi import Response

# Browsers revalidate after 1 minute; the CDN keeps 1 hour and may serve a stale copy for up
# to a day while it refreshes in the background. Data only changes when the admin writes.
PUBLIC_CACHE_CONTROL = "public, max-age=60, s-maxage=3600, stale-while-revalidate=86400"


def public_cache(response: Response) -> None:
    """Route dependency: set on successful responses only (errors build their own response)."""
    response.headers["Cache-Control"] = PUBLIC_CACHE_CONTROL


def no_store(response: Response) -> None:
    """Route dependency for admin responses: never cached by browsers or the CDN."""
    response.headers["Cache-Control"] = "no-store"
