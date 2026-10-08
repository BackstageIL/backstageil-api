"""Website rebuild hook (BSIL-46): the hook call, which requests count, the manual endpoint."""

import logging

import httpx2
import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.config import Settings
from app.core.exceptions import SiteRebuildFailedError
from app.core.security import hash_api_key
from app.main import create_app
from app.services.site_rebuild import (
    SiteRebuilder,
    changes_site_data,
    clean_hook_url,
    rebuilder_from_settings,
)

pytestmark = pytest.mark.anyio

HOOK = "https://api.vercel.com/v1/integrations/deploy/prj_test/s3cretHookId"
KEY = "unit-test-admin-key-0123456789abcdef"
AUTH = {"X-API-Key": KEY}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeRebuilder:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def trigger(self) -> None:
        self.calls += 1
        if self.fail:
            raise SiteRebuildFailedError("hook answered HTTP 500")


def admin_client(rebuilder: FakeRebuilder | None) -> TestClient:
    settings = Settings(
        _env_file=None, environment="ci", database_url=None, admin_api_key_hash=hash_api_key(KEY)
    )
    app = create_app(settings)
    app.state.site_rebuilder = rebuilder
    return TestClient(app)


# --- the hook call ------------------------------------------------------------------------------


async def test_trigger_posts_to_the_hook() -> None:
    requests: list[httpx2.Request] = []

    def answer(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(201, json={"job": {"state": "PENDING"}})

    await SiteRebuilder(HOOK, transport=httpx2.MockTransport(answer)).trigger()

    (request,) = requests
    assert (request.method, str(request.url)) == ("POST", HOOK)


@pytest.mark.parametrize("status", [404, 429, 500])
async def test_error_answer_fails_without_logging_the_hook(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    rebuilder = SiteRebuilder(
        HOOK, transport=httpx2.MockTransport(lambda r: httpx2.Response(status))
    )

    with caplog.at_level(logging.INFO), pytest.raises(SiteRebuildFailedError):
        await rebuilder.trigger()

    assert "s3cretHookId" not in caplog.text
    assert str(status) in caplog.text


async def test_network_failure_fails_without_logging_the_hook(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError(f"cannot reach {request.url}", request=request)

    rebuilder = SiteRebuilder(HOOK, transport=httpx2.MockTransport(fail))

    with caplog.at_level(logging.INFO), pytest.raises(SiteRebuildFailedError):
        await rebuilder.trigger()

    assert "s3cretHookId" not in caplog.text


async def test_failure_reason_never_contains_the_hook() -> None:
    answer_404 = httpx2.MockTransport(lambda r: httpx2.Response(404))
    with pytest.raises(SiteRebuildFailedError) as caught:
        await SiteRebuilder(HOOK, transport=answer_404).trigger()

    assert caught.value.details == {"reason": "hook answered HTTP 404"}
    assert "s3cretHookId" not in str(caught.value.details)


async def test_malformed_url_is_a_failure_not_a_crash() -> None:
    ok = httpx2.MockTransport(lambda r: httpx2.Response(200))

    with pytest.raises(SiteRebuildFailedError) as caught:
        await SiteRebuilder(f"{HOOK}\n", transport=ok).trigger()

    assert caught.value.details == {"reason": "hook request failed: InvalidURL"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (HOOK, HOOK),
        (f"  {HOOK}  ", HOOK),
        (f"{HOOK}\n", HOOK),
        (f'"{HOOK}"', HOOK),
        (f"'{HOOK}'\n", HOOK),
        ("http://api.vercel.com/v1/integrations/deploy/x", None),
        ("api.vercel.com/v1/integrations/deploy/x", None),
        ("https://api.vercel.com/v1/integrations/deploy/x y", None),
        ("   ", None),
    ],
)
def test_clean_hook_url(value: str, expected: str | None) -> None:
    assert clean_hook_url(value) == expected


def test_rebuilder_needs_the_setting() -> None:
    assert rebuilder_from_settings(Settings(_env_file=None)) is None
    assert rebuilder_from_settings(Settings(_env_file=None, site_deploy_hook_url="")) is None
    configured = Settings(_env_file=None, site_deploy_hook_url=f" {HOOK}\n")
    assert isinstance(rebuilder_from_settings(configured), SiteRebuilder)
    not_a_url = Settings(_env_file=None, site_deploy_hook_url="paste-error")
    assert rebuilder_from_settings(not_a_url) is None


# --- which requests change the site -------------------------------------------------------------


def request(method: str, path: str, query: str = "") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "query_string": query.encode(),
            "headers": [],
        }
    )


@pytest.mark.parametrize(
    ("method", "path", "query", "status", "expected"),
    [
        ("POST", "/api/v1/admin/venues/import", "publish=true", 200, True),
        ("POST", "/api/v1/admin/venues/import", "publish=true&dry_run=true", 200, False),
        ("POST", "/api/v1/admin/venues/import", "dry_run=1", 200, False),
        ("POST", "/api/v1/admin/venues/import", "dry_run=false", 200, True),
        ("PATCH", "/api/v1/admin/venues/x", "", 200, True),
        ("POST", "/api/v1/admin/venues/x/publish", "", 200, True),
        ("DELETE", "/api/v1/admin/venues/x", "confirm=x", 204, True),
        ("POST", "/api/v1/admin/venues/x/halls/main/pictures", "", 201, True),
        ("POST", "/api/v1/admin/venues/x/recommendations", "", 201, True),
        ("PATCH", "/api/v1/admin/venues/x", "", 422, False),
        ("DELETE", "/api/v1/admin/venues/x", "", 404, False),
        ("POST", "/api/v1/admin/venues/x/publish", "", 401, False),
        ("GET", "/api/v1/admin/venues", "", 200, False),
        ("GET", "/api/v1/admin/ping", "", 200, False),
        ("POST", "/api/v1/admin/site/rebuild", "", 202, False),  # triggers by itself
        ("POST", "/api/v1/venues", "", 200, False),  # not admin
        ("POST", "/api/v1/administrators", "", 200, False),  # prefix lookalike
    ],
)
def test_changes_site_data(method: str, path: str, query: str, status: int, expected: bool) -> None:
    assert changes_site_data(request(method, path, query), Response(status_code=status)) is expected


# --- endpoints and middleware without a database ------------------------------------------------


def test_manual_rebuild_triggers_once() -> None:
    rebuilder = FakeRebuilder()

    response = admin_client(rebuilder).post("/api/v1/admin/site/rebuild", headers=AUTH)

    assert response.status_code == 202
    assert response.json() == {"status": "triggered"}
    assert response.headers["cache-control"] == "no-store"
    assert rebuilder.calls == 1


def test_manual_rebuild_reports_missing_setting_and_failures() -> None:
    not_configured = admin_client(None).post("/api/v1/admin/site/rebuild", headers=AUTH)
    failing = admin_client(FakeRebuilder(fail=True)).post(
        "/api/v1/admin/site/rebuild", headers=AUTH
    )

    assert not_configured.status_code == 503
    assert not_configured.json()["error_code"] == "SITE_REBUILD_NOT_CONFIGURED"
    assert failing.status_code == 503
    assert failing.json()["error_code"] == "SITE_REBUILD_FAILED"
    assert failing.json()["details"] == {"reason": "hook answered HTTP 500"}


def test_manual_rebuild_requires_the_key() -> None:
    rebuilder = FakeRebuilder()

    response = admin_client(rebuilder).post("/api/v1/admin/site/rebuild")

    assert response.status_code == 401
    assert rebuilder.calls == 0


def test_failed_admin_write_does_not_rebuild() -> None:
    rebuilder = FakeRebuilder()

    # No database configured: the write fails with 503, so nothing changed
    response = admin_client(rebuilder).patch(
        "/api/v1/admin/venues/x", json={"name": "Renamed"}, headers=AUTH
    )

    assert response.status_code == 503
    assert rebuilder.calls == 0
