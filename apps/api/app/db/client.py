"""MongoDB connection management.

Two client flavours, deliberately:

* :func:`get_async_database` — used by the API. Request handling is I/O-bound
  and concurrent, which is exactly what ``AsyncMongoClient`` is for. PyMongo
  4.13+ ships it as GA, so **Motor is not used**: the officially supported
  async interface is now in the driver itself (see ADR-0004).
* :func:`sync_database` — used by the ingestion CLI and benchmarks. Those are
  batch processes with no concurrency to exploit; async would add machinery and
  no throughput.

Nothing outside this package constructs a client. The browser never connects to
MongoDB at all — the API is the sole database client (SECURITY.md).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from pymongo import AsyncMongoClient, MongoClient
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Bounded so a database outage surfaces as a fast, clear error instead of a
# request that hangs until the client gives up (SOUL.md §5).
_CONNECT_TIMEOUT_MS = 5_000
_SERVER_SELECTION_TIMEOUT_MS = 5_000

_async_client: AsyncMongoClient[dict[str, Any]] | None = None


def _client_options(settings: Settings) -> dict[str, Any]:
    """Connection options shared by both client flavours."""
    return {
        "connectTimeoutMS": _CONNECT_TIMEOUT_MS,
        "serverSelectionTimeoutMS": _SERVER_SELECTION_TIMEOUT_MS,
        "tz_aware": True,  # BSON dates come back as aware UTC (ADR-0009)
        "appname": f"navisight-{settings.app_env}",
    }


def get_async_client() -> AsyncMongoClient[dict[str, Any]]:
    """Return the process-wide async client, creating it on first use."""
    global _async_client
    if _async_client is None:
        settings = get_settings()
        _async_client = AsyncMongoClient(settings.mongodb_uri, **_client_options(settings))
    return _async_client


def get_async_database() -> AsyncDatabase[dict[str, Any]]:
    """Return the application database for async (API) use."""
    return get_async_client()[get_settings().mongodb_database]


async def close_async_client() -> None:
    """Close the async client. Called from the API lifespan shutdown hook."""
    global _async_client
    if _async_client is not None:
        await _async_client.close()
        _async_client = None


async def ping() -> bool:
    """Whether the database is reachable.

    Used by the readiness probe. Returns ``False`` rather than raising, because
    "not ready" is a normal state the API reports, not an error it crashes on.
    """
    try:
        await get_async_client().admin.command("ping")
    except PyMongoError as exc:
        logger.warning("mongodb_ping_failed", extra={"error": str(exc)})
        return False
    return True


@contextmanager
def sync_database(*, database_name: str | None = None) -> Iterator[Database[dict[str, Any]]]:
    """Yield a synchronous database handle, closing the client on exit.

    For the CLI and benchmarks. ``database_name`` overrides the configured
    database, which is how integration tests target ``MONGODB_TEST_DATABASE``
    instead of real data.
    """
    settings = get_settings()
    client: MongoClient[dict[str, Any]] = MongoClient(
        settings.mongodb_uri, **_client_options(settings)
    )
    try:
        yield client[database_name or settings.mongodb_database]
    finally:
        client.close()


def server_version(database: Database[dict[str, Any]]) -> str:
    """MongoDB server version, recorded alongside benchmark results.

    A performance number without the server version it was measured on is not
    reproducible (SOUL.md §13).
    """
    info = database.client.server_info()
    return str(info.get("version", "unknown"))
