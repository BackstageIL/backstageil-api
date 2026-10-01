import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import FailedAttemptLimiter, api_key_matches, hash_api_key
from app.main import create_app
from scripts.new_admin_key import new_admin_key

KEY = "correct-horse-battery-staple-key"
PING = "/api/v1/admin/ping"


def make_client(key_hash: str | None = hash_api_key(KEY), max_failures: int = 3) -> TestClient:
    settings = Settings(
        _env_file=None,
        environment="ci",
        database_url=None,
        admin_api_key_hash=key_hash,
        admin_max_failed_attempts=max_failures,
        admin_failed_window_seconds=60,
    )
    return TestClient(create_app(settings))


def test_hash_and_match() -> None:
    key_hash = hash_api_key(KEY)

    assert len(key_hash) == 64
    assert api_key_matches(KEY, key_hash)
    assert not api_key_matches(KEY + "x", key_hash)


def test_new_admin_key_is_long_random_and_matches_its_hash() -> None:
    key, key_hash = new_admin_key()
    other_key, _ = new_admin_key()

    assert len(key) >= 40
    assert key != other_key
    assert api_key_matches(key, key_hash)


def test_valid_key_is_accepted_and_not_cached() -> None:
    response = make_client().get(PING, headers={"X-API-Key": KEY})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}, {"X-API-Key": ""}])
def test_missing_or_wrong_key_is_401(headers: dict[str, str]) -> None:
    response = make_client().get(PING, headers=headers)

    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_admin_disabled_when_no_hash_is_configured() -> None:
    response = make_client(key_hash=None).get(PING, headers={"X-API-Key": KEY})

    assert response.status_code == 503
    assert response.json()["error_code"] == "ADMIN_NOT_CONFIGURED"


def test_repeated_failures_are_blocked_even_with_the_right_key() -> None:
    client = make_client(max_failures=3)
    for _ in range(3):
        assert client.get(PING, headers={"X-API-Key": "wrong"}).status_code == 401

    blocked = client.get(PING, headers={"X-API-Key": KEY})

    assert blocked.status_code == 429
    assert blocked.json()["error_code"] == "TOO_MANY_ATTEMPTS"
    assert 1 <= int(blocked.headers["retry-after"]) <= 60


def test_successful_requests_do_not_count_as_failures() -> None:
    client = make_client(max_failures=2)
    for _ in range(5):
        assert client.get(PING, headers={"X-API-Key": KEY}).status_code == 200


def test_limiter_window_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [1000.0]
    monkeypatch.setattr("app.core.security.time.monotonic", lambda: now[0])
    limiter = FailedAttemptLimiter(max_attempts=2, window_seconds=60)

    limiter.record_failure("1.2.3.4")
    limiter.record_failure("1.2.3.4")
    assert limiter.retry_after("1.2.3.4") == 61
    assert limiter.retry_after("5.6.7.8") == 0  # other clients unaffected

    now[0] += 60
    assert limiter.retry_after("1.2.3.4") == 0


@pytest.mark.parametrize("bad_hash", ["not-a-hash", "A" * 64, "a" * 63])
def test_invalid_hash_setting_is_rejected(bad_hash: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, admin_api_key_hash=bad_hash)


def test_empty_hash_setting_means_admin_disabled() -> None:
    assert Settings(_env_file=None, admin_api_key_hash="").admin_api_key_hash is None
