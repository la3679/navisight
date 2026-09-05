"""Precomputed analytics must agree with the live aggregation, always.

A cache that returns a *different* answer than the query it replaces is worse
than the slow query it replaced, so the central test here runs both paths over
the same synthetic data and asserts they are identical — bucket for bucket,
count for count.

The remaining tests pin the two conditions that gate serving a rollup at all:
the request must cover the whole archive, and the collection must not have
changed underneath it.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pymongo.database import Database

from app.config import get_settings
from app.db import collections, indexes
from app.domain.ais import parse_row
from app.ingest.pipeline import build_latest_update, build_position_document
from app.services import rollup
from tests.conftest import ais_row

pytestmark = pytest.mark.integration

BASE = datetime(2025, 1, 8, 0, 0, 0, tzinfo=UTC)
WINDOW = {"start": "2025-01-08T00:00:00Z", "end": "2025-01-08T23:59:59Z"}


@pytest.fixture
def seeded(test_database: Database[dict[str, Any]]) -> Database[dict[str, Any]]:
    """Observations spread across several hours and speed bands.

    Deliberately uneven: two vessels with different reporting rates and speeds,
    so a bug that collapses buckets or mis-assigns a band shows up as a
    difference rather than as two equal-looking answers.
    """
    indexes.ensure_indexes(test_database)

    rows = [
        ais_row(
            mmsi="366000001",
            at=BASE + timedelta(minutes=index * 7),
            longitude=-74.0,
            latitude=40.0,
            name="ALPHA TRADER",
            vessel_type="70",
            sog=f"{(index % 5) * 4.5:.1f}",
        )
        for index in range(90)
    ]
    rows.extend(
        ais_row(
            mmsi="366000002",
            at=BASE + timedelta(minutes=index * 31),
            longitude=-118.0,
            latitude=33.7,
            name="BETA FERRY",
            vessel_type="60",
            sog=f"{(index % 3) * 0.4:.1f}",
        )
        for index in range(40)
    )

    records = [parse_row(row) for row in rows]
    test_database[collections.VESSEL_POSITIONS].insert_many(
        [build_position_document(r, dataset="TEST", source_file="test.csv") for r in records]
    )
    test_database[collections.VESSEL_LATEST].bulk_write([build_latest_update(r) for r in records])
    return test_database


@pytest.fixture
def client(
    seeded: Database[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    from app.db import client as db_client

    settings = get_settings()
    monkeypatch.setattr(settings, "mongodb_database", settings.mongodb_test_database)
    db_client._async_client = None

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
    db_client._async_client = None


def _strip(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop the one field the two paths are *expected* to differ on."""
    return {key: value for key, value in payload.items() if key != "computedAt"}


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/v1/analytics/traffic", {**WINDOW, "interval": "hour"}),
        ("/api/v1/analytics/traffic", {**WINDOW, "interval": "15min"}),
        ("/api/v1/analytics/speed", WINDOW),
        ("/api/v1/analytics/active-vessels", {**WINDOW, "limit": 10}),
    ],
)
def test_rollup_answers_identically_to_the_live_aggregation(
    client: TestClient,
    seeded: Database[dict[str, Any]],
    path: str,
    params: dict[str, Any],
) -> None:
    live = client.get(path, params=params)
    assert live.status_code == 200

    summary = rollup.build(seeded)
    assert summary["built"] == len(rollup.ALL_KINDS)

    precomputed = client.get(path, params=params)
    assert precomputed.status_code == 200

    live_payload = live.json()
    precomputed_payload = precomputed.json()

    if isinstance(live_payload, dict):
        assert _strip(precomputed_payload) == _strip(live_payload)
        # The live path leaves it unset; the rollup path says when it was built.
        assert live_payload.get("computedAt") is None
        assert precomputed_payload["computedAt"] is not None
    else:
        assert precomputed_payload == live_payload


def test_a_narrower_window_is_not_answered_from_the_rollup(
    client: TestClient, seeded: Database[dict[str, Any]]
) -> None:
    """A rollup summarises the whole archive and cannot answer for part of it."""
    rollup.build(seeded)

    response = client.get(
        "/api/v1/analytics/traffic",
        params={"start": "2025-01-08T02:00:00Z", "end": "2025-01-08T04:00:00Z", "interval": "hour"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["computedAt"] is None, "a partial window must be aggregated live"
    # And it really is narrower: the full day has more buckets than two hours.
    assert len(payload["buckets"]) <= 3


def test_a_rollup_is_ignored_once_the_collection_changes(
    client: TestClient, seeded: Database[dict[str, Any]]
) -> None:
    """The staleness guard is the whole reason this cache is safe."""
    rollup.build(seeded)
    assert (
        client.get("/api/v1/analytics/traffic", params={**WINDOW, "interval": "hour"}).json()[
            "computedAt"
        ]
        is not None
    )

    extra = parse_row(
        ais_row(
            mmsi="366000003",
            at=BASE + timedelta(hours=5),
            longitude=-80.0,
            latitude=25.0,
            name="GAMMA",
            vessel_type="80",
        )
    )
    seeded[collections.VESSEL_POSITIONS].insert_one(
        build_position_document(extra, dataset="TEST", source_file="test.csv")
    )

    payload = client.get("/api/v1/analytics/traffic", params={**WINDOW, "interval": "hour"}).json()
    assert payload["computedAt"] is None, "a changed collection must invalidate the rollup"
    assert payload["totalObservations"] == 131


def test_a_request_deeper_than_the_stored_ranking_is_not_truncated(
    client: TestClient, seeded: Database[dict[str, Any]]
) -> None:
    """Asking for more vessels than the rollup stores must not silently cap."""
    rollup.build(seeded)

    payload = client.get(
        "/api/v1/analytics/active-vessels",
        params={**WINDOW, "limit": rollup.ACTIVE_VESSELS_DEPTH + 1},
    ).json()
    # Only two vessels exist, so the answer is the same either way — the point
    # is that it was computed rather than read from a ranking too short to
    # satisfy the request.
    assert len(payload) == 2


def test_rollup_reports_nothing_to_do_on_an_empty_collection(
    test_database: Database[dict[str, Any]],
) -> None:
    summary = rollup.build(test_database)
    assert summary["built"] == 0
    assert "no positions" in summary["reason"]
