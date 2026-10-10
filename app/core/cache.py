"""HTTP cache headers for public, read-only endpoints."""

from fastapi import Response

# Only browsers may keep an answer (1 minute); "private" stops Vercel's CDN from storing it (it
# would otherwise reuse max-age for itself). The website is built from this API right after each
# admin write (BSIL-46), and a CDN copy would make that build publish old data (BSIL-53).
# Visitors never call the API, so nothing is lost.
PUBLIC_CACHE_CONTROL = "private, max-age=60"


def public_cache(response: Response) -> None:
    """Route dependency: set on successful responses only (errors build their own response)."""
    response.headers["Cache-Control"] = PUBLIC_CACHE_CONTROL


def no_store(response: Response) -> None:
    """Route dependency for admin responses: never cached by browsers or the CDN."""
    response.headers["Cache-Control"] = "no-store"
