"""Consistent API error responses.

Every error the API returns has the same shape, so a client can handle failures
uniformly instead of pattern-matching on prose:

.. code-block:: json

    {"error": {"code": "VESSEL_NOT_FOUND",
               "message": "Vessel was not found.",
               "requestId": "9f2c1a...",
               "details": {"mmsi": "366000001"}}}

``message`` is written for a person to read. It never contains a stack trace, a
database error string, or anything else that leaks internals — an unexpected
exception is logged in full server-side and reported to the client as a generic
internal error with the request id to correlate against.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.observability import request_id_var


class ErrorCode(StrEnum):
    """Stable, machine-readable error identifiers."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    VESSEL_NOT_FOUND = "VESSEL_NOT_FOUND"
    PORT_NOT_FOUND = "PORT_NOT_FOUND"
    NOT_FOUND = "NOT_FOUND"
    DATASET_EMPTY = "DATASET_EMPTY"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    AI_NOT_CONFIGURED = "AI_NOT_CONFIGURED"
    AI_ERROR = "AI_ERROR"
    RANGE_TOO_LARGE = "RANGE_TOO_LARGE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    request_id: str = Field(serialization_alias="requestId")
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """The envelope every error response uses."""

    error: ErrorBody


class ApiError(Exception):
    """An error with a client-safe message and a stable code."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class VesselNotFoundError(ApiError):
    def __init__(self, mmsi: str) -> None:
        super().__init__(
            ErrorCode.VESSEL_NOT_FOUND,
            "No vessel with that MMSI exists in the imported dataset.",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"mmsi": mmsi},
        )


class DatabaseUnavailableError(ApiError):
    def __init__(self) -> None:
        super().__init__(
            ErrorCode.DATABASE_UNAVAILABLE,
            "The database is not reachable. Check that MongoDB is running.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class AiNotConfiguredError(ApiError):
    def __init__(self) -> None:
        super().__init__(
            ErrorCode.AI_NOT_CONFIGURED,
            (
                "The AI copilot is not configured. Set LLM_PROVIDER, LLM_MODEL, and "
                "LLM_API_KEY, or use LLM_PROVIDER=mock for an offline demo."
            ),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


def error_response(
    code: ErrorCode,
    message: str,
    *,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build the standard error envelope."""
    body = ErrorBody(code=code, message=message, request_id=request_id_var.get(), details=details)
    return JSONResponse(
        status_code=status_code,
        content={"error": body.model_dump(by_alias=True, exclude_none=True)},
    )


async def api_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Render an :class:`ApiError`."""
    assert isinstance(exc, ApiError)
    return error_response(exc.code, exc.message, status_code=exc.status_code, details=exc.details)


async def validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Render FastAPI/Pydantic validation failures in the standard envelope.

    Bounds violations (a radius over the maximum, a page size too large) arrive
    here, so the client learns *which* parameter was wrong rather than getting
    an opaque 422.
    """
    assert isinstance(exc, RequestValidationError)
    fields = [
        {
            "field": ".".join(str(part) for part in error["loc"][1:]) or str(error["loc"]),
            "problem": error["msg"],
        }
        for error in exc.errors()
    ]
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        "One or more request parameters are invalid.",
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        details={"fields": fields},
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    """Last resort.

    The exception is logged with its traceback server-side; the client gets a
    generic message plus the request id, and no internal detail.
    """
    import logging

    logging.getLogger(__name__).exception("unhandled_exception", exc_info=exc)
    return error_response(
        ErrorCode.INTERNAL_ERROR,
        "An unexpected error occurred. Quote the request id if you report this.",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
