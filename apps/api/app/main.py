"""FastAPI application entry point.

    uv run uvicorn app.main:app --reload

The app starts even when MongoDB is down and even when no LLM is configured.
Both are reported through ``/api/v1/ready`` and ``/api/v1/dataset/status`` so
the frontend can render an informative state — crashing on startup would just
turn a recoverable situation into an opaque one (SOUL.md §11).
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import build_openapi_tags
from app.api.v1.router import router as v1_router
from app.config import get_settings
from app.db.client import close_async_client, ping
from app.errors import (
    ApiError,
    api_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.observability import configure_logging, new_request_id, request_id_var, scrub

logger = logging.getLogger(__name__)

DESCRIPTION = """
Maritime vessel and port intelligence over **historical** AIS broadcast data.

The dataset is a single archived day of AIS observations, filtered by the
publisher to one-minute resolution. This API therefore reports a vessel's
*latest observation in the imported dataset* — never a live or current
position. Endpoints and field names use that vocabulary deliberately.

Every list endpoint is bounded: result limits, geospatial radii, time ranges,
and trajectory point counts all have enforced server-side maximums. Trajectory
responses always state their raw point count and simplification method, so a
simplified path is never mistaken for complete telemetry.
""".strip()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Configure logging on startup and close the database client on shutdown."""
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)
    logger.info(
        "api_starting",
        extra={
            "version": __version__,
            "env": settings.app_env,
            "database": settings.mongodb_database,
        },
    )
    if not await ping():
        # A warning, not a failure: the API serves its status endpoints so the
        # UI can explain what is wrong.
        logger.warning("mongodb_unreachable_at_startup", extra={"uri_configured": True})
    if not settings.ai_enabled:
        logger.info("ai_provider_not_configured")
    try:
        yield
    finally:
        await close_async_client()
        logger.info("api_stopped")


app = FastAPI(
    title="NaviSight API",
    description=DESCRIPTION,
    version=__version__,
    openapi_tags=build_openapi_tags(),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

_settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    # An explicit origin list, never "*": the browser must not be able to call
    # this API from an arbitrary page.
    allow_origins=_settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Attach a request id, time the request, and log the outcome.

    An inbound ``X-Request-ID`` is honoured so a trace can span the frontend and
    the API, but it is scrubbed first — it is untrusted input that ends up in
    log lines.
    """
    inbound = request.headers.get("X-Request-ID")
    request_id = scrub(inbound, max_length=64) if inbound else new_request_id()
    token = request_id_var.set(request_id)
    started = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - started) * 1000
        logger.exception(
            "request_failed",
            extra={
                "method": request.method,
                "route": request.url.path,
                "duration_ms": round(duration_ms, 2),
            },
        )
        raise
    finally:
        request_id_var.reset(token)

    duration_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    # Path only, never the query string: query parameters can contain
    # user-supplied search terms.
    logger.info(
        "request",
        extra={
            "method": request.method,
            "route": request.url.path,
            "status": response.status_code,
            "duration_ms": round(duration_ms, 2),
        },
    )
    return response


app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

app.include_router(v1_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """Point a curious browser at the docs."""
    return {
        "name": "NaviSight API",
        "version": __version__,
        "docs": "/docs",
        "health": "/api/v1/health",
        "note": "Serves historical AIS data. Not a live vessel feed.",
    }
