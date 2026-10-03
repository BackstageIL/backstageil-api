import json
from collections.abc import Iterator
from typing import Any

import pytest
import sentry_sdk
from fastapi.testclient import TestClient
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from app.core.config import Settings
from app.core.monitoring import init_error_tracking
from app.main import create_app

# The example DSN from Sentry's docs: nothing is ever sent (the transport below keeps events)
DSN = "https://examplePublicKey@o0.ingest.sentry.io/0"
ADMIN_KEY = "admin-key-that-must-never-leave"


class KeepEvents(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        event = envelope.get_event()
        if event is not None:
            self.events.append(dict(event))


@pytest.fixture
def transport() -> Iterator[KeepEvents]:
    keep = KeepEvents()
    yield keep
    sentry_sdk.init()  # back to a disabled client for the other tests


def test_tracking_is_off_without_a_dsn() -> None:
    assert init_error_tracking(Settings(_env_file=None, sentry_dsn="")) is False


def test_create_app_starts_error_tracking(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Settings] = []
    monkeypatch.setattr("app.main.init_error_tracking", seen.append)
    settings = Settings(_env_file=None)

    create_app(settings)

    assert seen == [settings]


def test_unhandled_error_is_reported_without_credentials(
    transport: KeepEvents, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "abc123")
    settings = Settings(_env_file=None, environment="production", sentry_dsn=DSN)
    assert init_error_tracking(settings, transport=transport) is True

    app = create_app(Settings(_env_file=None, database_url=None))

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("something broke")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            "/boom", headers={"X-API-Key": ADMIN_KEY, "Authorization": f"Bearer {ADMIN_KEY}"}
        )
    sentry_sdk.flush()

    assert response.status_code == 500
    assert len(transport.events) == 1
    event = transport.events[0]
    assert event["exception"]["values"][0]["value"] == "something broke"
    assert event["environment"] == "production"
    assert event["release"] == "abc123"
    assert ADMIN_KEY not in json.dumps(event, default=str)


def test_client_errors_are_not_reported(transport: KeepEvents) -> None:
    init_error_tracking(Settings(_env_file=None, sentry_dsn=DSN), transport=transport)

    with TestClient(create_app(Settings(_env_file=None, database_url=None))) as client:
        assert client.get("/api/v1/does-not-exist").status_code == 404
        assert client.post("/health").status_code == 405
    sentry_sdk.flush()

    assert transport.events == []


def test_server_side_unavailability_is_reported(transport: KeepEvents) -> None:
    init_error_tracking(Settings(_env_file=None, sentry_dsn=DSN), transport=transport)

    with TestClient(create_app(Settings(_env_file=None, database_url=None))) as client:
        assert client.get("/health/ready").status_code == 503  # no database configured
    sentry_sdk.flush()

    assert len(transport.events) == 1
