"""Error tracking with Sentry (free tier). Off unless SENTRY_DSN is set."""

import os
from typing import Any

import sentry_sdk

from app.core.config import Settings


def init_error_tracking(settings: Settings, **options: Any) -> bool:
    """Report server errors (unhandled exceptions and 5xx answers) to Sentry; True if on."""
    if settings.sentry_dsn is None:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn.get_secret_value(),
        environment=settings.environment,
        # Vercel sets the deployed commit, so each error points to the code that raised it
        release=os.environ.get("VERCEL_GIT_COMMIT_SHA"),
        # No IPs, cookies or credentials: the X-API-Key and Authorization headers are dropped
        send_default_pii=False,
        # No stack-frame variables either: they hold raw request headers, settings and URLs
        include_local_variables=False,
        # Errors only, no performance tracing: stays well inside the free quota
        traces_sample_rate=0.0,
        **options,
    )
    return True
