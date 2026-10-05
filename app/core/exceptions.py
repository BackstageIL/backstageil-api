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
    UNKNOWN_CITY = "UNKNOWN_CITY"
    VENUE_NOT_FOUND = "VENUE_NOT_FOUND"
    HALL_NOT_FOUND = "HALL_NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    TOO_MANY_ATTEMPTS = "TOO_MANY_ATTEMPTS"
    ADMIN_NOT_CONFIGURED = "ADMIN_NOT_CONFIGURED"
    DUPLICATE_SLUGS = "DUPLICATE_SLUGS"
    CONFIRMATION_MISMATCH = "CONFIRMATION_MISMATCH"
    PICTURE_NOT_FOUND = "PICTURE_NOT_FOUND"
    INVALID_PICTURE = "INVALID_PICTURE"
    PICTURE_TOO_LARGE = "PICTURE_TOO_LARGE"
    TOO_MANY_PICTURES = "TOO_MANY_PICTURES"
    DUPLICATE_PICTURE = "DUPLICATE_PICTURE"
    PICTURES_NOT_CONFIGURED = "PICTURES_NOT_CONFIGURED"
    PICTURE_STORAGE_UNAVAILABLE = "PICTURE_STORAGE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorType(StrEnum):
    AUTH = "AUTH"
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


class UnknownCityError(DomainException):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error_code = ErrorCode.UNKNOWN_CITY
    error_type = ErrorType.VALIDATION

    def __init__(self, city_code: int) -> None:
        super().__init__(
            f"No city with official code {city_code} (seed it with scripts.seed_cities --code)",
            details={"city_code": city_code},
        )


class VenueNotFoundError(DomainException):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = ErrorCode.VENUE_NOT_FOUND
    error_type = ErrorType.NOT_FOUND

    def __init__(self, venue_slug: str) -> None:
        super().__init__(f"Venue '{venue_slug}' not found", details={"venue": venue_slug})


class HallNotFoundError(DomainException):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = ErrorCode.HALL_NOT_FOUND
    error_type = ErrorType.NOT_FOUND

    def __init__(self, venue_slug: str, hall_slug: str) -> None:
        super().__init__(
            f"Hall '{hall_slug}' not found in venue '{venue_slug}'",
            details={"venue": venue_slug, "hall": hall_slug},
        )


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


class UnauthorizedError(DomainException):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = ErrorCode.UNAUTHORIZED
    error_type = ErrorType.AUTH

    def __init__(self) -> None:
        super().__init__("Missing or invalid X-API-Key")


class TooManyAttemptsError(DomainException):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = ErrorCode.TOO_MANY_ATTEMPTS
    error_type = ErrorType.AUTH

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(
            "Too many failed attempts; try again later",
            details={"retry_after_seconds": retry_after_seconds},
        )

    def to_response(self) -> JSONResponse:
        response = super().to_response()
        response.headers["Retry-After"] = str(self.details["retry_after_seconds"])
        return response


class AdminNotConfiguredError(DomainException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = ErrorCode.ADMIN_NOT_CONFIGURED
    error_type = ErrorType.UNAVAILABLE

    def __init__(self) -> None:
        super().__init__("Admin access is not configured (ADMIN_API_KEY_HASH is not set)")


class DuplicateSlugsError(DomainException):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error_code = ErrorCode.DUPLICATE_SLUGS
    error_type = ErrorType.VALIDATION

    def __init__(self, slugs: list[str]) -> None:
        super().__init__(
            "The upload contains the same venue slug more than once", details={"slugs": slugs}
        )


class ConfirmationMismatchError(DomainException):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error_code = ErrorCode.CONFIRMATION_MISMATCH
    error_type = ErrorType.VALIDATION

    def __init__(self, expected: str) -> None:
        super().__init__(
            f"To delete, repeat the slug: ?confirm={expected}", details={"expected": expected}
        )


class PictureNotFoundError(DomainException):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = ErrorCode.PICTURE_NOT_FOUND
    error_type = ErrorType.NOT_FOUND

    def __init__(self, picture_id: int) -> None:
        super().__init__(f"Picture {picture_id} not found", details={"picture_id": picture_id})


class InvalidPictureError(DomainException):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error_code = ErrorCode.INVALID_PICTURE
    error_type = ErrorType.VALIDATION


class PictureTooLargeError(DomainException):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    error_code = ErrorCode.PICTURE_TOO_LARGE
    error_type = ErrorType.VALIDATION

    def __init__(self, max_bytes: int) -> None:
        super().__init__(
            f"The file is larger than {max_bytes // (1024 * 1024)} MB; shrink it before uploading",
            details={"max_bytes": max_bytes},
        )


class TooManyPicturesError(DomainException):
    status_code = status.HTTP_409_CONFLICT
    error_code = ErrorCode.TOO_MANY_PICTURES
    error_type = ErrorType.CONFLICT

    def __init__(self, limit: int) -> None:
        super().__init__(
            f"A hall can have at most {limit} pictures; delete one first", details={"limit": limit}
        )


class DuplicatePictureError(DomainException):
    status_code = status.HTTP_409_CONFLICT
    error_code = ErrorCode.DUPLICATE_PICTURE
    error_type = ErrorType.CONFLICT

    def __init__(self, picture_id: int) -> None:
        super().__init__(
            "This picture was already uploaded", details={"existing_picture_id": picture_id}
        )


class PicturesNotConfiguredError(DomainException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = ErrorCode.PICTURES_NOT_CONFIGURED
    error_type = ErrorType.UNAVAILABLE

    def __init__(self, missing: str) -> None:
        super().__init__(f"Pictures are not configured ({missing} is not set)")


class PictureStorageUnavailableError(DomainException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = ErrorCode.PICTURE_STORAGE_UNAVAILABLE
    error_type = ErrorType.UNAVAILABLE

    def __init__(self) -> None:
        super().__init__("Picture storage is unavailable; try again later")
