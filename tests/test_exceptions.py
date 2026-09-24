from typing import NoReturn

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError, IntegrityError


def _add_failing_route(app: FastAPI, path: str, exc: Exception) -> None:
    async def fail() -> NoReturn:
        raise exc

    app.add_api_route(path, fail, response_model=None)


def test_integrity_error_is_409(app: FastAPI) -> None:
    _add_failing_route(app, "/boom", IntegrityError("INSERT ...", {}, Exception("duplicate key")))

    response = TestClient(app).get("/boom")

    assert response.status_code == 409
    assert response.json()["error_code"] == "DUPLICATE_ENTRY"


def test_database_error_is_500_without_leaking_details(app: FastAPI) -> None:
    _add_failing_route(app, "/boom", DBAPIError("SELECT secret_column", {}, Exception("oops")))

    response = TestClient(app).get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "DATABASE_ERROR"
    assert "secret_column" not in response.text


def test_unhandled_error_is_generic_500(app: FastAPI) -> None:
    _add_failing_route(app, "/boom", RuntimeError("internal detail"))

    response = TestClient(app, raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert response.json()["error_code"] == "INTERNAL_ERROR"
    assert "internal detail" not in response.text
