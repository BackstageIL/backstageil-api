"""
Admin authentication: a single admin API key sent as `X-API-Key`.

Only a salted scrypt hash of the key is configured (ADMIN_API_KEY_HASH), in the format
`scrypt$<n>$<r>$<p>$<salt>$<hash>` (base64url). scrypt is deliberately slow, so the hash stays
safe even if a weak key were ever set by hand; comparison is constant-time.
Repeated wrong keys from one client address are answered with 429 for a while.
"""

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from typing import Annotated

from fastapi import Depends, Header, Request

from app.core.config import Settings
from app.core.exceptions import AdminNotConfiguredError, TooManyAttemptsError, UnauthorizedError
from app.core.logger import get_logger

logger = get_logger(__name__)

# scrypt cost: ~16 MB memory, a few tens of ms per check (admin requests are rare)
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _SCRYPT_LEN = 2**14, 8, 1, 32


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _scrypt(key: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(key.encode(), salt=salt, n=n, r=r, p=p, dklen=_SCRYPT_LEN)


def hash_api_key(key: str) -> str:
    """Salted scrypt hash of the key, with its parameters, as one string."""
    salt = secrets.token_bytes(16)
    digest = _scrypt(key, salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def api_key_matches(key: str, stored_hash: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored_hash.split("$")
        if scheme != "scrypt":
            return False
        computed = _scrypt(key, _unb64(salt), int(n), int(r), int(p))
        return hmac.compare_digest(computed, _unb64(digest))
    except ValueError:
        return False


class FailedAttemptLimiter:
    """In-memory sliding window of failed attempts per client address (per app instance)."""

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _recent(self, client: str, now: float) -> deque[float]:
        failures = self._failures[client]
        while failures and now - failures[0] >= self.window_seconds:
            failures.popleft()
        return failures

    def retry_after(self, client: str) -> int:
        """Seconds until this client may try again (0 = allowed now)."""
        now = time.monotonic()
        failures = self._recent(client, now)
        if len(failures) < self.max_attempts:
            return 0
        return max(1, int(self.window_seconds - (now - failures[0])) + 1)

    def record_failure(self, client: str) -> None:
        self._failures[client].append(time.monotonic())


def _client_address(request: Request) -> str:
    # Behind the platform proxy, uvicorn --proxy-headers puts the real address here.
    return request.client.host if request.client else "unknown"


def require_admin(
    request: Request,
    x_api_key: Annotated[str | None, Header(description="Admin API key")] = None,
) -> None:
    """Route dependency for admin-only endpoints."""
    settings: Settings = request.app.state.settings
    if settings.admin_api_key_hash is None:
        raise AdminNotConfiguredError()

    limiter: FailedAttemptLimiter = request.app.state.admin_limiter
    client = _client_address(request)
    wait = limiter.retry_after(client)
    if wait:
        raise TooManyAttemptsError(wait)

    if x_api_key is None or not api_key_matches(x_api_key, settings.admin_api_key_hash):
        limiter.record_failure(client)
        logger.warning("Rejected admin request from %s", client)
        raise UnauthorizedError()


AdminRequired = Annotated[None, Depends(require_admin)]
