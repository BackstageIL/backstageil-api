"""
Rebuild the website after admin changes (BSIL-46).

The website is built from this API at build time, so it is rebuilt through its Vercel deploy hook
whenever an admin write succeeds. Vercel cancels superseded hook builds, so several quick edits
end in one live build. The hook URL is a secret: it is never logged.
"""

from collections.abc import Awaitable, Callable
from contextlib import suppress

import httpx2
from fastapi import FastAPI, Request, Response

from app.core.config import Settings
from app.core.exceptions import SiteRebuildFailedError
from app.core.logger import get_logger

logger = get_logger(__name__)

ADMIN_PREFIX = "/api/v1/admin"
MANUAL_REBUILD_PATH = f"{ADMIN_PREFIX}/site/rebuild"
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_TRUE = frozenset({"1", "true", "t", "yes", "y", "on"})  # how FastAPI reads a true bool query


class SiteRebuilder:
    """Calls the website's deploy hook. `transport` is for tests."""

    def __init__(self, hook_url: str, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self._hook_url = hook_url
        self._transport = transport

    async def trigger(self) -> None:
        transport = self._transport or httpx2.AsyncHTTPTransport(retries=2)
        try:
            async with httpx2.AsyncClient(transport=transport, timeout=10) as client:
                response = await client.post(self._hook_url)
                response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            logger.error("Site rebuild hook answered %s", exc.response.status_code)
            raise SiteRebuildFailedError() from exc
        except httpx2.HTTPError as exc:
            logger.error("Site rebuild hook request failed: %s", exc.__class__.__name__)
            raise SiteRebuildFailedError() from exc
        logger.info("Site rebuild triggered")


def rebuilder_from_settings(settings: Settings) -> SiteRebuilder | None:
    if settings.site_deploy_hook_url is None:
        return None
    return SiteRebuilder(settings.site_deploy_hook_url.get_secret_value())


def changes_site_data(request: Request, response: Response) -> bool:
    """A successful admin write, other than a dry run or the manual rebuild itself."""
    path = request.url.path
    return (
        path.startswith(f"{ADMIN_PREFIX}/")
        and path != MANUAL_REBUILD_PATH
        and request.method in _WRITE_METHODS
        and 200 <= response.status_code < 300
        and request.query_params.get("dry_run", "").lower() not in _TRUE
    )


def add_rebuild_after_admin_writes(app: FastAPI) -> None:
    """Middleware: after a successful admin write, rebuild the site (best effort)."""

    @app.middleware("http")
    async def rebuild_after_admin_writes(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        rebuilder: SiteRebuilder | None = request.app.state.site_rebuilder
        if rebuilder is not None and changes_site_data(request, response):
            # A failure is logged; the data change itself succeeded and is returned as is.
            with suppress(SiteRebuildFailedError):
                await rebuilder.trigger()
        return response
