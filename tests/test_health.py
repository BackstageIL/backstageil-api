from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.dependencies import get_database


class FakeDatabase:
    def __init__(self, *, reachable: bool) -> None:
        self.reachable = reachable

    async def ping(self) -> None:
        if not self.reachable:
            raise ConnectionError("connection refused")


def test_liveness_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_without_database_is_503(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["error_code"] == "DATABASE_NOT_CONFIGURED"
    assert body["error_type"] == "UNAVAILABLE"


def test_readiness_with_reachable_database_is_ok(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[get_database] = lambda: FakeDatabase(reachable=True)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_with_unreachable_database_is_503(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[get_database] = lambda: FakeDatabase(reachable=False)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["error_code"] == "DATABASE_UNAVAILABLE"


def test_unknown_route_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/does-not-exist").status_code == 404


def test_openapi_docs_available(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "BackstageIL API"
