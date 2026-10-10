"""HTTP cache headers for public, read-only endpoints."""

from fastapi import Response

# Browsers may keep an answer for 1 minute. No s-maxage, so Vercel's CDN doesn't store it: the
# website is built from this API right after each admin write (BSIL-46), and a CDN copy would
# make that build publish old data (BSIL-53). Visitors never call the API, so nothing is lost.
PUBLIC_CACHE_CONTROL = "public, max-age=60"


def public_cache(response: Response) -> None:
    """Route dependency: set on successful responses only (errors build their own response)."""
    response.headers["Cache-Control"] = PUBLIC_CACHE_CONTROL


def no_store(response: Response) -> None:
    """Route dependency for admin responses: never cached by browsers or the CDN."""
    response.headers["Cache-Control"] = "no-store"
