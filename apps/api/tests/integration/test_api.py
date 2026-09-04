"""API contract tests.

Run against a small synthetic dataset in the test database, never the real
5.9M-row file. They assert the properties a client depends on:

* the error envelope is consistent and leaks nothing internal;
* every bound is actually enforced, not merely documented;
* historical vocabulary is used in the payloads;
* a simplified track always declares that it was simplified.
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
from app.ingest.pipeline import build_latest_update, build_position_document
from app.domain.ais import parse_row
from tests.conftest import ais_row

pytestmark = pytest.mark.integration

BASE = datetime(2025, 1, 8, 12, 0, 0, tzinfo=UTC)

#: ALPHA TRADER walks 60 minutes north-east from (-74.0, 40.0) in 0.005 deg
#: steps, so its newest observation -- the one geo queries see -- is here.
ALPHA_LATEST = (-74.0 + 59 * 0.005, 40.0 + 59 * 0.005)


@pytest.fixture
def client(
    test_database: Database[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """A TestClient wired to the throwaway test database."""
    from app.db import client as db_client

    settings = get_settings()
    monkeypatch.setattr(settings, "mongodb_database", settings.mongodb_test_database)
    db_client._async_client = None  # force a fresh client bound to the test db

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
    db_client._async_client = None


@pytest.fixture
def seeded(test_database: Database[dict[str, Any]]) -> Database[dict[str, Any]]:
    """Two vessels with a short track each, written through the real builders.

    Using the production document builders keeps the fixture honest: if the
    stored shape changes, these tests see the same change the app does.
    """
    indexes.ensure_indexes(test_database)
    rows = []
    for index in range(60):
        rows.append(
            ais_row(
                mmsi="366000001",
                at=BASE + timedelta(minutes=index),
                longitude=-74.0 + index * 0.005,
                latitude=40.0 + index * 0.005,
                name="ALPHA TRADER",
                vessel_type="70",
            )
        )
    for index in range(10):
        rows.append(
            ais_row(
                mmsi="366000002",
                at=BASE + timedelta(minutes=index),
                longitude=-118.0,
                latitude=33.7,
                name="BETA FERRY",
                vessel_type="60",
                transceiver="B",
            )
        )

    records = [parse_row(row) for row in rows]
    test_database[collections.VESSEL_POSITIONS].insert_many(
        [build_position_document(r, dataset="TEST", source_file="test.csv") for r in records]
    )
    test_database[collections.VESSEL_LATEST].bulk_write(
        [build_latest_update(r) for r in records], ordered=True
    )
    test_database[collections.VESSELS].insert_many(
        [
            {
                "_id": "366000001",
                "mmsi": "366000001",
                "name": "ALPHA TRADER",
                "nameNormalized": "ALPHA TRADER",
                "callSign": "TEST1",
                "vesselType": 70,
                "dimensions": {"lengthMeters": 100, "widthMeters": 20, "draftMeters": 5.0},
                "firstSeenAt": BASE,
                "lastSeenAt": BASE + timedelta(minutes=59),
            },
            {
                "_id": "366000002",
                "mmsi": "366000002",
                "name": "BETA FERRY",
                "nameNormalized": "BETA FERRY",
                "vesselType": 60,
                "firstSeenAt": BASE,
                "lastSeenAt": BASE + timedelta(minutes=9),
            },
        ]
    )
    return test_database


class TestSystem:
    def test_health_does_not_require_a_database(self, client: TestClient) -> None:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_ready_reports_degraded_rather_than_failing(self, client: TestClient) -> None:
        """An empty database is a state to report, not an error to raise."""
        response = client.get("/api/v1/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["hasData"] is False

    def test_every_response_carries_a_request_id(self, client: TestClient) -> None:
        response = client.get("/api/v1/health")
        assert response.headers["X-Request-ID"]


class TestErrorEnvelope:
    def test_unknown_vessel_returns_the_standard_envelope(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        response = client.get("/api/v1/vessels/999999999")
        assert response.status_code == 404
        error = response.json()["error"]
        assert error["code"] == "VESSEL_NOT_FOUND"
        assert error["requestId"]
        assert error["details"]["mmsi"] == "999999999"

    def test_validation_failure_names_the_offending_field(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/geo/nearby", params={"longitude": -74, "latitude": 40, "radiusKm": 99999}
        )
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert error["details"]["fields"][0]["field"] == "radiusKm"

    def test_error_messages_do_not_leak_internals(self, client: TestClient) -> None:
        response = client.get("/api/v1/vessels/999999999")
        message = response.json()["error"]["message"]
        for leak in ("Traceback", "pymongo", "mongodb://", "app/services"):
            assert leak not in message


class TestBoundsAreEnforced:
    @pytest.mark.parametrize(
        ("path", "params"),
        [
            ("/api/v1/vessels", {"limit": 100_000}),
            ("/api/v1/geo/nearby", {"longitude": 0, "latitude": 0, "radiusKm": 10_000}),
            ("/api/v1/geo/nearby", {"longitude": 999, "latitude": 0, "radiusKm": 10}),
            (
                "/api/v1/map/vessels",
                {"west": -1, "south": -1, "east": 1, "north": 1, "limit": 1_000_000},
            ),
            ("/api/v1/vessels/366000001/track", {"max_points": 100_000}),
            ("/api/v1/vessels/366000001/positions", {"limit": 100_000}),
        ],
    )
    def test_over_limit_requests_are_rejected(
        self, client: TestClient, path: str, params: dict[str, Any]
    ) -> None:
        """There must be no way to ask the API for an unbounded scan."""
        assert client.get(path, params=params).status_code == 422

    def test_an_excessive_time_range_is_rejected(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        response = client.get(
            "/api/v1/analytics/traffic",
            params={"start": "2000-01-01T00:00:00Z", "end": "2025-01-08T00:00:00Z"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "RANGE_TOO_LARGE"

    def test_a_regex_in_the_search_term_is_rejected(self, client: TestClient) -> None:
        """A user string must never become a pattern the database evaluates."""
        response = client.get("/api/v1/vessels", params={"q": ".*"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_a_non_numeric_mmsi_is_rejected_by_the_path_pattern(self, client: TestClient) -> None:
        assert client.get("/api/v1/vessels/abc%24where").status_code == 422


class TestVessels:
    def test_search_matches_a_name_prefix(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        response = client.get("/api/v1/vessels", params={"q": "ALPHA"})
        assert response.status_code == 200
        assert [item["mmsi"] for item in response.json()] == ["366000001"]

    def test_search_is_case_insensitive(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        assert len(client.get("/api/v1/vessels", params={"q": "alpha"}).json()) == 1

    def test_search_matches_an_exact_mmsi(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        response = client.get("/api/v1/vessels", params={"q": "366000002"})
        assert [item["mmsi"] for item in response.json()] == ["366000002"]

    def test_vessel_detail_includes_type_label_and_dimensions(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        body = client.get("/api/v1/vessels/366000001").json()
        assert body["vesselType"] == {"code": 70, "label": "Cargo", "family": "Cargo"}
        assert body["dimensions"]["lengthMeters"] == 100
        assert body["observationCount"] == 60

    def test_missing_metadata_serializes_as_null_not_a_placeholder_value(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        """The API returns null; the UI renders an em dash. Never 0, never "N/A"."""
        body = client.get("/api/v1/vessels/366000002").json()
        assert body["imo"] is None
        assert body["callSign"] is None

    def test_latest_observation_is_the_newest_event(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        body = client.get("/api/v1/vessels/366000001/latest").json()
        assert body["timestamp"].startswith("2025-01-08T12:59")

    def test_positions_are_returned_newest_first(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        items = client.get("/api/v1/vessels/366000001/positions", params={"limit": 5}).json()[
            "items"
        ]
        timestamps = [item["timestamp"] for item in items]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_pagination_cursor_advances_without_repeating(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        first = client.get("/api/v1/vessels/366000001/positions", params={"limit": 10}).json()
        assert first["page"]["hasMore"] is True
        second = client.get(
            "/api/v1/vessels/366000001/positions",
            params={"limit": 10, "cursor": first["page"]["nextCursor"]},
        ).json()
        first_ids = {item["timestamp"] for item in first["items"]}
        second_ids = {item["timestamp"] for item in second["items"]}
        assert not (first_ids & second_ids)

    def test_an_invalid_cursor_is_rejected_cleanly(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        response = client.get(
            "/api/v1/vessels/366000001/positions", params={"cursor": "not-a-cursor"}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


class TestTrackHonesty:
    def test_an_unsimplified_track_says_so(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        meta = client.get("/api/v1/vessels/366000001/track", params={"max_points": 1000}).json()[
            "meta"
        ]
        assert meta["simplified"] is False
        assert meta["method"] == "none"
        assert meta["rawPointCount"] == meta["returnedPointCount"] == 60

    def test_a_simplified_track_declares_the_method_and_raw_count(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        """SOUL.md §4: a simplified path is never presented as complete telemetry."""
        body = client.get("/api/v1/vessels/366000001/track", params={"max_points": 10}).json()
        meta = body["meta"]
        assert meta["rawPointCount"] == 60
        assert meta["returnedPointCount"] <= 10
        assert meta["simplified"] is True
        assert meta["method"] in {"douglas_peucker", "uniform_sample"}
        assert len(body["points"]) == meta["returnedPointCount"]

    def test_tracks_are_never_interpolated(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        meta = client.get("/api/v1/vessels/366000001/track").json()["meta"]
        assert meta["interpolated"] is False

    def test_track_points_are_chronological(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        points = client.get("/api/v1/vessels/366000001/track").json()["points"]
        timestamps = [point["timestamp"] for point in points]
        assert timestamps == sorted(timestamps)


class TestGeo:
    def test_nearby_returns_distance_sorted_results(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        results = client.get(
            "/api/v1/geo/nearby",
            params={"longitude": -74.0, "latitude": 40.0, "radiusKm": 500},
        ).json()
        distances = [item["distanceKm"] for item in results]
        assert distances == sorted(distances)

    def test_nearby_reports_both_units(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        """Marine work uses nautical miles; km is offered alongside, both labelled."""
        result = client.get(
            "/api/v1/geo/nearby",
            params={"longitude": -74.0, "latitude": 40.0, "radiusKm": 500},
        ).json()[0]
        assert result["distanceKm"] > 0
        # Both values are rounded to 3 decimals independently, so the tolerance
        # has to be looser than that rounding.
        assert result["distanceNauticalMiles"] == pytest.approx(
            result["distanceKm"] / 1.852, abs=0.002
        )

    def test_nearby_excludes_vessels_outside_the_radius(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        """Queried at ALPHA's latest position, so only it is within 10 km.

        ALPHA's track ends at ALPHA_LATEST, ~41 km from its start -- proximity is
        evaluated against latest known state, not first observation. BETA sits
        off California, thousands of km away.
        """
        results = client.get(
            "/api/v1/geo/nearby",
            params={
                "longitude": ALPHA_LATEST[0],
                "latitude": ALPHA_LATEST[1],
                "radiusKm": 10,
            },
        ).json()
        assert {item["vessel"]["mmsi"] for item in results} == {"366000001"}

    def test_nearby_returns_nothing_in_empty_water(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        results = client.get(
            "/api/v1/geo/nearby",
            params={"longitude": 0.0, "latitude": 0.0, "radiusKm": 100},
        ).json()
        assert results == []

    def test_map_viewport_returns_only_vessels_inside_it(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        body = client.get(
            "/api/v1/map/vessels",
            params={"west": -75, "south": 39, "east": -73, "north": 41},
        ).json()
        assert {vessel["mmsi"] for vessel in body["vessels"]} == {"366000001"}

    def test_an_antimeridian_viewport_is_handled_rather_than_inverted(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        """west > east means the box wraps. A naive query would return the
        complement — every vessel in the seeded set instead of none."""
        body = client.get(
            "/api/v1/map/vessels",
            params={"west": 170, "south": 39, "east": -170, "north": 41},
        ).json()
        assert body["vessels"] == []
        assert body["totalInViewport"] == 0


class TestAnalytics:
    def test_vessel_type_distribution_counts_vessels_and_says_so(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        body = client.get("/api/v1/analytics/vessel-types").json()
        assert body["total"] == 2
        assert "vessel_latest" in body["basis"]
        assert {item["key"] for item in body["categories"]} == {"Cargo", "Passenger"}

    def test_traffic_buckets_are_chronological_and_counted(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        body = client.get(
            "/api/v1/analytics/traffic",
            params={"start": "2025-01-08T00:00:00Z", "end": "2025-01-09T00:00:00Z"},
        ).json()
        assert body["totalObservations"] == 70
        buckets = [bucket["bucket"] for bucket in body["buckets"]]
        assert buckets == sorted(buckets)

    def test_active_vessels_are_ranked_by_observation_count(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        body = client.get(
            "/api/v1/analytics/active-vessels",
            params={"start": "2025-01-08T00:00:00Z", "end": "2025-01-09T00:00:00Z"},
        ).json()
        assert body[0]["vessel"]["mmsi"] == "366000001"
        assert body[0]["observations"] == 60


class TestHistoricalVocabulary:
    def test_dataset_status_declares_the_data_historical(
        self, client: TestClient, seeded: Database[dict[str, Any]]
    ) -> None:
        body = client.get("/api/v1/dataset/status").json()
        assert body["isHistorical"] is True
        assert body["hasData"] is True

    def test_the_openapi_description_never_claims_live_data(self, client: TestClient) -> None:
        """ADR-0008, enforced mechanically rather than by review discipline."""
        document = client.get("/openapi.json").json()
        text = str(document).lower()
        for forbidden in ("real-time", "live tracking", "live vessel", "currently at sea"):
            assert forbidden not in text, f"API documentation claims {forbidden!r}"
