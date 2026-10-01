import httpx2
import pytest

from scripts import smoke_test
from scripts.smoke_test import CHECKS, run_checks


def make_client(
    handler: httpx2.MockTransport, headers: dict[str, str] | None = None
) -> httpx2.Client:
    return httpx2.Client(base_url="https://deploy.test", transport=handler, headers=headers or {})


def healthy(request: httpx2.Request) -> httpx2.Response:
    path = request.url.path
    if path == "/api/v1/venues":
        return httpx2.Response(200, json={"items": [{}], "total": 21})
    if path == "/api/v1/cities":
        return httpx2.Response(200, json=[{"slug": "haifa"}])
    if path in ("/health", "/health/ready"):
        return httpx2.Response(200, json={"status": "ok"})
    return httpx2.Response(404, json={})


def test_all_checks_pass_on_a_healthy_deployment() -> None:
    with make_client(httpx2.MockTransport(healthy)) as client:
        assert run_checks(client, CHECKS, delay_seconds=0) == []


def test_failures_are_reported() -> None:
    def no_data(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/health/ready":
            return httpx2.Response(503, json={})
        if request.url.path == "/api/v1/venues":
            return httpx2.Response(200, json={"items": [], "total": 0})
        return healthy(request)

    with make_client(httpx2.MockTransport(no_data)) as client:
        failures = run_checks(client, CHECKS, attempts=2, delay_seconds=0)

    assert failures == ["/health/ready: HTTP 503", "/api/v1/venues?limit=1: unexpected content"]


def test_cold_start_is_retried() -> None:
    calls = {"n": 0}

    def cold_then_ok(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx2.Response(503)
        return healthy(request)

    with make_client(httpx2.MockTransport(cold_then_ok)) as client:
        assert run_checks(client, CHECKS[:1], attempts=3, delay_seconds=0) == []


def test_main_sends_the_bypass_header_and_exits_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str | None] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers.get("x-vercel-protection-bypass"))
        return healthy(request)

    real_client = httpx2.Client

    def fake_client(**kwargs: object) -> httpx2.Client:
        return real_client(transport=httpx2.MockTransport(handler), **kwargs)  # type: ignore[arg-type]

    monkeypatch.setenv("VERCEL_AUTOMATION_BYPASS_SECRET", "bypass-123")
    monkeypatch.setattr("scripts.smoke_test.httpx2.Client", fake_client)
    monkeypatch.setattr("scripts.smoke_test.time.sleep", lambda _seconds: None)

    smoke_test.main(["https://deploy.test"])  # healthy: no exit
    assert seen and all(value == "bypass-123" for value in seen)

    with pytest.raises(SystemExit, match="Smoke test failed"):
        smoke_test.main(["https://deploy.test", "--fail-on-purpose"])
