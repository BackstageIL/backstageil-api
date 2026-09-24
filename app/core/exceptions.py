"""
Domain exceptions and their HTTP mapping.

Services raise DomainException subclasses (framework-agnostic); each one knows its HTTP status,
so adding a new error never requires touching the handlers. Every error response has the shape:
{"error_code": ..., "error_type": ..., "message": ..., "details": {...}}
"""

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.logger import get_logger

logger = get_logger(__name__)


class ErrorCode(StrEnum):
    DATABASE_NOT_CONFIGURED = "DATABASE_NOT_CONFIGURED"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    DATABASE_ERROR = "DATABASE_ERROR"
    DUPLICATE_ENTRY = "DUPLICATE_ENTRY"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorType(StrEnum):
    NOT_FOUND = "NOT_FOUND"
    VALIDATION = "VALIDATION"
    CONFLICT = "CONFLICT"
    UNAVAILABLE = "UNAVAILABLE"
    INTERNAL = "INTERNAL"


def error_response(
    status_code: int,
    error_code: ErrorCode,
    error_type: ErrorType,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error_code,
            "error_type": error_type,
            "message": message,
            "details": details or {},
        },
    )


class DomainException(Exception):
    """Base class for errors raised by services and dependencies."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: ErrorCode = ErrorCode.INTERNAL_ERROR
    error_type: ErrorType = ErrorType.INTERNAL

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_response(self) -> JSONResponse:
        return error_response(
            self.status_code, self.error_code, self.error_type, self.message, self.details
        )


class DatabaseNotConfiguredError(DomainException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = ErrorCode.DATABASE_NOT_CONFIGURED
    error_type = ErrorType.UNAVAILABLE

    def __init__(self) -> None:
        super().__init__("Database is not configured (DATABASE_URL is not set)")


class DatabaseUnavailableError(DomainException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = ErrorCode.DATABASE_UNAVAILABLE
    error_type = ErrorType.UNAVAILABLE

    def __init__(self) -> None:
        super().__init__("Database is unavailable")


async def _domain_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainException)
    return exc.to_response()


async def _integrity_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.warning("Integrity error: %s", exc)
    return error_response(
        status.HTTP_409_CONFLICT, ErrorCode.DUPLICATE_ENTRY, ErrorType.CONFLICT, "Duplicate entry"
    )


async def _database_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.error("Database error: %s", exc)
    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        ErrorCode.DATABASE_ERROR,
        ErrorType.INTERNAL,
        "Database error",
    )


async def _unhandled_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", exc_info=exc)
    return error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        ErrorCode.INTERNAL_ERROR,
        ErrorType.INTERNAL,
        "Internal server error",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainException, _domain_exception_handler)
    app.add_exception_handler(IntegrityError, _integrity_error_handler)
    app.add_exception_handler(DBAPIError, _database_error_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
