from typing import Any

import httpx2
import pytest

from scripts import promote as promote_script
from scripts.promote import PromoteError, deployment_host, promote

DEPLOYMENT_URL = "https://backstageil-abc123-team.vercel.app"


class FakeVercel:
    """Answers the three API calls; `project_states` are returned one per project poll."""

    def __init__(self, *project_states: dict[str, Any], target: str = "production") -> None:
        self.project_states = list(project_states)
        self.target = target
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/v13/deployments/backstageil-abc123-team.vercel.app":
            return httpx2.Response(200, json={"id": "dpl_new", "target": self.target})
        if path == "/v10/projects/prj_1/promote/dpl_new" and request.method == "POST":
            return httpx2.Response(201)
        if path == "/v9/projects/prj_1":
            state = (
                self.project_states.pop(0)
                if len(self.project_states) > 1
                else self.project_states[0]
            )
            return httpx2.Response(200, json=state)
        return httpx2.Response(404, json={"error": {"code": "not_found", "message": "Not found"}})


def make_client(fake: FakeVercel) -> httpx2.Client:
    return httpx2.Client(base_url="https://api.vercel.test", transport=httpx2.MockTransport(fake))


def alias_request(status: str, deployment_id: str = "dpl_new") -> dict[str, Any]:
    return {"lastAliasRequest": {"jobStatus": status, "toDeploymentId": deployment_id}}


def test_promotes_and_waits_until_production_serves_the_deployment() -> None:
    fake = FakeVercel(
        alias_request("in-progress", "dpl_old"),
        alias_request("pending"),
        alias_request("succeeded"),
    )
    with make_client(fake) as client:
        assert promote(client, "prj_1", DEPLOYMENT_URL, poll_seconds=0) == "dpl_new"

    calls = [(r.method, r.url.path) for r in fake.requests]
    assert calls[:2] == [
        ("GET", "/v13/deployments/backstageil-abc123-team.vercel.app"),
        ("POST", "/v10/projects/prj_1/promote/dpl_new"),
    ]
    assert len(calls) == 5


def test_production_target_counts_as_done() -> None:
    fake = FakeVercel({"targets": {"production": {"id": "dpl_new"}}})
    with make_client(fake) as client:
        assert promote(client, "prj_1", DEPLOYMENT_URL, poll_seconds=0) == "dpl_new"


def test_failed_promotion_raises() -> None:
    with (
        make_client(FakeVercel(alias_request("failed"))) as client,
        pytest.raises(PromoteError, match="failed"),
    ):
        promote(client, "prj_1", DEPLOYMENT_URL, poll_seconds=0)


def test_times_out_when_never_done() -> None:
    with (
        make_client(FakeVercel(alias_request("pending"))) as client,
        pytest.raises(PromoteError, match="not finished"),
    ):
        promote(client, "prj_1", DEPLOYMENT_URL, timeout_seconds=0, poll_seconds=0)


def test_preview_deployment_is_refused_before_promoting() -> None:
    fake = FakeVercel(alias_request("succeeded"), target="preview")
    with (
        make_client(fake) as client,
        pytest.raises(PromoteError, match="not a production deployment"),
    ):
        promote(client, "prj_1", DEPLOYMENT_URL, poll_seconds=0)
    assert all(r.method == "GET" for r in fake.requests)


def test_api_errors_show_vercel_message() -> None:
    fake = FakeVercel(alias_request("succeeded"))
    with make_client(fake) as client, pytest.raises(PromoteError, match="HTTP 404 Not found"):
        promote(client, "prj_other", DEPLOYMENT_URL, poll_seconds=0)


def test_deployment_host_accepts_url_or_host() -> None:
    assert deployment_host(DEPLOYMENT_URL) == "backstageil-abc123-team.vercel.app"
    assert (
        deployment_host("backstageil-abc123-team.vercel.app")
        == "backstageil-abc123-team.vercel.app"
    )


def test_main_uses_team_and_token_and_exits_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeVercel(alias_request("succeeded"))
    real_client = httpx2.Client

    def fake_client(**kwargs: Any) -> httpx2.Client:
        return real_client(transport=httpx2.MockTransport(fake), **kwargs)

    monkeypatch.setenv("VERCEL_TOKEN", "tok-123")
    monkeypatch.setenv("VERCEL_ORG_ID", "team_1")
    monkeypatch.setenv("VERCEL_PROJECT_ID", "prj_1")
    monkeypatch.setattr("scripts.promote.httpx2.Client", fake_client)
    monkeypatch.setattr("scripts.promote.time.sleep", lambda _seconds: None)

    promote_script.main([DEPLOYMENT_URL])
    assert all(r.headers["authorization"] == "Bearer tok-123" for r in fake.requests)
    assert all(r.url.params["teamId"] == "team_1" for r in fake.requests)

    monkeypatch.setenv("VERCEL_PROJECT_ID", "prj_other")
    with pytest.raises(SystemExit, match="Promote failed"):
        promote_script.main([DEPLOYMENT_URL])


def test_main_requires_the_vercel_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    monkeypatch.setenv("VERCEL_ORG_ID", "team_1")
    monkeypatch.setenv("VERCEL_PROJECT_ID", "prj_1")
    with pytest.raises(SystemExit, match="VERCEL_TOKEN"):
        promote_script.main([DEPLOYMENT_URL])
