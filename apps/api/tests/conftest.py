"""Shared test fixtures.

Integration tests need a running MongoDB and use a **separate** database
(``MONGODB_TEST_DATABASE``) which is dropped between runs. They are skipped
automatically when no server is reachable, so ``pytest`` still works on a
machine without MongoDB — CI runs the unit suite unconditionally and the
integration suite only where a server is provisioned.

No test ever touches the real 5.9M-row dataset (SOUL.md §17, ADR-0007).
Fixtures here are synthetic and hand-checkable.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError

from app.config import get_settings
from app.domain.ais import EXPECTED_COLUMNS


@pytest.fixture(scope="session")
def mongo_client() -> Iterator[MongoClient[dict[str, Any]]]:
    """Session-scoped client, skipping every integration test if unreachable."""
    settings = get_settings()
    client: MongoClient[dict[str, Any]] = MongoClient(
        settings.mongodb_uri,
        serverSelectionTimeoutMS=2_000,
        # Must match app.db.client: without it BSON dates come back naive and
        # every timestamp assertion compares a naive value against an aware one
        # (ADR-0009 — a naive datetime is a bug, including in tests).
        tz_aware=True,
    )
    try:
        client.admin.command("ping")
    except PyMongoError as exc:
        client.close()
        pytest.skip(f"MongoDB is not reachable at {settings.mongodb_uri}: {exc}")
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def test_database(
    mongo_client: MongoClient[dict[str, Any]],
) -> Iterator[Database[dict[str, Any]]]:
    """A clean test database per test.

    Dropped before *and* after, so a crashed run cannot leak state into the
    next one. This is never the application database.
    """
    settings = get_settings()
    name = settings.mongodb_test_database
    assert name != settings.mongodb_database, (
        "MONGODB_TEST_DATABASE must differ from MONGODB_DATABASE — "
        "integration tests drop the database they run against."
    )
    mongo_client.drop_database(name)
    try:
        yield mongo_client[name]
    finally:
        mongo_client.drop_database(name)


def write_ais_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    """Write a synthetic AIS CSV with the real 2025+ schema and CRLF endings.

    Matching the real file's dialect matters: the source uses CRLF, and a
    fixture that used LF would not exercise the same parsing path.
    """
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(EXPECTED_COLUMNS), lineterminator="\r\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in EXPECTED_COLUMNS})
    return path


def ais_row(
    mmsi: str = "366000001",
    *,
    at: datetime | None = None,
    # str is accepted so fixtures can inject deliberately invalid values
    # ("", "999") to exercise the rejection paths.
    longitude: float | str = -74.0,
    latitude: float | str = 40.0,
    sog: str = "10.0",
    name: str = "TEST VESSEL",
    vessel_type: str = "70",
    transceiver: str = "A",
    **overrides: str,
) -> dict[str, str]:
    """Build one synthetic AIS row. Defaults are deliberately plausible."""
    moment = at or datetime(2025, 1, 8, 12, 0, 0, tzinfo=UTC)
    row = {
        "mmsi": mmsi,
        "base_date_time": moment.strftime("%Y-%m-%d %H:%M:%S"),
        "longitude": f"{longitude}",
        "latitude": f"{latitude}",
        "sog": sog,
        "cog": "90.0",
        "heading": "90",
        "vessel_name": name,
        "imo": "",
        "call_sign": "TEST1",
        "vessel_type": vessel_type,
        "status": "0",
        "length": "100",
        "width": "20",
        "draft": "5.0",
        "cargo": "70",
        "transceiver": transceiver,
    }
    row.update(overrides)
    return row


def minutes(count: int) -> timedelta:
    """Readable time offsets in fixtures."""
    return timedelta(minutes=count)
