"""Integration tests for the ingestion pipeline.

These cover the properties that are easy to get wrong and expensive to discover
later:

* idempotency — re-running an import must not duplicate anything;
* resume — a crash between the write and the checkpoint must not lose or
  duplicate data;
* out-of-order safety — the source is not chronologically ordered, so
  ``vessel_latest`` must reflect the newest *event time*, not the last row
  written;
* rejection accounting — bad rows are counted, not silently dropped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pymongo.database import Database

from app.db import collections, indexes
from app.ingest.pipeline import ingest
from tests.conftest import ais_row, minutes, write_ais_csv

pytestmark = pytest.mark.integration

BASE = datetime(2025, 1, 8, 12, 0, 0, tzinfo=UTC)


def run_ingest(path: Path, database: Database[dict[str, Any]], **kwargs: Any) -> Any:
    """Ingest with test-friendly defaults."""
    kwargs.setdefault("dataset", "TEST")
    kwargs.setdefault("batch_size", 100)
    return ingest(path, database, **kwargs)


class TestIdempotency:
    def test_reimporting_the_same_file_creates_no_duplicates(
        self, tmp_path: Path, test_database: Database[dict[str, Any]]
    ) -> None:
        """The core guarantee from ADR-0006."""
        rows = [ais_row(at=BASE + minutes(i), longitude=-74.0 + i * 0.01) for i in range(50)]
        source = write_ais_csv(tmp_path / "ais.csv", rows)
        indexes.ensure_indexes(test_database)

        first = run_ingest(source, test_database)
        assert first.positions_inserted == 50
        assert first.positions_duplicate == 0

        second = run_ingest(source, test_database)
        assert second.positions_inserted == 0
        assert second.positions_duplicate == 50

        assert test_database[collections.VESSEL_POSITIONS].count_documents({}) == 50

    def test_identical_rows_collapse_to_one_document(
        self, tmp_path: Path, test_database: Database[dict[str, Any]]
    ) -> None:
        """1,112 such rows exist in the real dataset; collapsing them is correct."""
        row = ais_row(at=BASE)
        source = write_ais_csv(tmp_path / "ais.csv", [row, row, row])
        stats = run_ingest(source, test_database)

        assert stats.rows_valid == 3
        assert stats.positions_inserted == 1
        assert stats.positions_duplicate == 2
        assert test_database[collections.VESSEL_POSITIONS].count_documents({}) == 1

    def test_same_mmsi_and_timestamp_with_different_position_are_kept_apart(
        self, tmp_path: Path, test_database: Database[dict[str, Any]]
    ) -> None:
        """318 such rows exist in the real dataset. They are distinct events and
        must NOT be collapsed — this is why the fingerprint includes position."""
        source = write_ais_csv(
            tmp_path / "ais.csv",
            [
                ais_row(at=BASE, longitude=-74.0, latitude=40.0),
                ais_row(at=BASE, longitude=-74.5, latitude=40.5),
            ],
        )
        stats = run_ingest(source, test_database)

        assert stats.positions_inserted == 2
        assert stats.positions_duplicate == 0


class TestOutOfOrderSafety:
    def test_latest_state_reflects_newest_event_not_last_row(
        self, tmp_path: Path, test_database: Database[dict[str, Any]]
    ) -> None:
        """The source file is not time-ordered, so arrival order must not win.

        The newest observation appears FIRST in the file here; a naive
        last-write-wins implementation would leave the older position stored.
        """
        source = write_ais_csv(
            tmp_path / "ais.csv",
            [
                ais_row(at=BASE + minutes(60), longitude=-70.0, latitude=41.0, sog="15.0"),
                ais_row(at=BASE, longitude=-74.0, latitude=40.0, sog="5.0"),
                ais_row(at=BASE + minutes(30), longitude=-72.0, latitude=40.5, sog="10.0"),
            ],
        )
        run_ingest(source, test_database)

        latest = test_database[collections.VESSEL_LATEST].find_one({"_id": "366000001"})
        assert latest is not None
        assert latest["timestamp"] == BASE + minutes(60)
        assert latest["location"]["coordinates"] == [-70.0, 41.0]
        assert latest["speedOverGroundKnots"] == 15.0

    def test_a_later_import_of_older_data_does_not_regress_state(
        self, tmp_path: Path, test_database: Database[dict[str, Any]]
    ) -> None:
        """Importing an older file after a newer one must be a no-op for state."""
        newer = write_ais_csv(
            tmp_path / "newer.csv",
            [ais_row(at=BASE + minutes(60), longitude=-70.0, latitude=41.0)],
        )
        older = write_ais_csv(
            tmp_path / "older.csv", [ais_row(at=BASE, longitude=-74.0, latitude=40.0)]
        )
        run_ingest(newer, test_database)
        run_ingest(older, test_database)

        latest = test_database[collections.VESSEL_LATEST].find_one({"_id": "366000001"})
        assert latest is not None
        assert latest["timestamp"] == BASE + minutes(60), "older data regressed latest state"
        # Both observations are still stored as history.
        assert test_database[collections.VESSEL_POSITIONS].count_documents({}) == 2

    def test_out_of_order_rows_do_not_regress_across_checkpoint_flushes(
        self, tmp_path: Path, test_database: Database[dict[str, Any]]
    ) -> None:
        """The newest event is in the FIRST flush window and the oldest in the
        last, so the guarantee has to hold across separate bulk writes, not just
        within one in-memory window."""
        rows = [ais_row(at=BASE + minutes(500), longitude=-60.0, latitude=45.0)]
        rows += [ais_row(at=BASE + minutes(i), longitude=-74.0 + i * 0.001) for i in range(400)]
        source = write_ais_csv(tmp_path / "ais.csv", rows)
        run_ingest(source, test_database, batch_size=50, checkpoint_rows=100)

        latest = test_database[collections.VESSEL_LATEST].find_one({"_id": "366000001"})
        assert latest is not None
        assert latest["timestamp"] == BASE + minutes(500)


class TestResume:
    def test_resume_skips_already_processed_rows_and_loses_nothing(
        self, tmp_path: Path, test_database: Database[dict[str, Any]]
    ) -> None:
        rows = [ais_row(at=BASE + minutes(i), longitude=-74.0 + i * 0.01) for i in range(100)]
        source = write_ais_csv(tmp_path / "ais.csv", rows)

        partial = run_ingest(source, test_database, limit=40)
        assert partial.positions_inserted == 40

        resumed = run_ingest(source, test_database, resume_from_row=40)
        assert resumed.rows_skipped_resume == 40
        assert resumed.positions_inserted == 60
        assert test_database[collections.VESSEL_POSITIONS].count_documents({}) == 100

    def test_resuming_from_a_stale_checkpoint_is_safe(
        self, tmp_path: Path, test_database: Database[dict[str, Any]]
    ) -> None:
        """Simulates a crash after writing a batch but before the checkpoint.

        Resuming from the older checkpoint replays rows that are already stored.
        Idempotency must turn those into duplicates, not into extra documents.
        """
        rows = [ais_row(at=BASE + minutes(i), longitude=-74.0 + i * 0.01) for i in range(100)]
        source = write_ais_csv(tmp_path / "ais.csv", rows)

        run_ingest(source, test_database, limit=60)
        # The checkpoint we resume from is behind what was actually written.
        resumed = run_ingest(source, test_database, resume_from_row=30)

        assert resumed.positions_duplicate == 30, "replayed rows should be duplicates"
        assert resumed.positions_inserted == 40
        assert test_database[collections.VESSEL_POSITIONS].count_documents({}) == 100


class TestRejectionAccounting:
    def test_bad_rows_are_counted_by_reason_not_silently_dropped(
        self, tmp_path: Path, test_database: Database[dict[str, Any]]
    ) -> None:
        source = write_ais_csv(
            tmp_path / "ais.csv",
            [
                ais_row(at=BASE),
                ais_row(at=BASE + minutes(1), base_date_time="not-a-date"),
                ais_row(at=BASE + minutes(2), longitude=""),
                ais_row(at=BASE + minutes(3), latitude="999"),
                ais_row(at=BASE + minutes(4), mmsi=""),
            ],
        )
        stats = run_ingest(source, test_database)

        assert stats.rows_read == 5
        assert stats.rows_valid == 1
        assert stats.rows_rejected == 4
        assert stats.reject_reasons == {
            "invalid_timestamp": 1,
            "missing_coordinate": 1,
            "coordinate_out_of_range": 1,
            "missing_mmsi": 1,
        }
        assert test_database[collections.VESSEL_POSITIONS].count_documents({}) == 1


class TestStoredShape:
    def test_position_documents_store_geojson_in_longitude_latitude_order(
        self, tmp_path: Path, test_database: Database[dict[str, Any]]
    ) -> None:
        source = write_ais_csv(
            tmp_path / "ais.csv", [ais_row(at=BASE, longitude=-74.25, latitude=38.5)]
        )
        run_ingest(source, test_database)

        document = test_database[collections.VESSEL_POSITIONS].find_one({})
        assert document is not None
        assert document["location"] == {"type": "Point", "coordinates": [-74.25, 38.5]}

    def test_absent_values_are_omitted_rather_than_stored_as_null(
        self, tmp_path: Path, test_database: Database[dict[str, Any]]
    ) -> None:
        """Heading is absent in 50.6% of real rows. It must not become 0 or null."""
        source = write_ais_csv(
            tmp_path / "ais.csv",
            [ais_row(at=BASE, heading="", status="", sog="")],
        )
        run_ingest(source, test_database)

        document = test_database[collections.VESSEL_POSITIONS].find_one({})
        assert document is not None
        navigation = document.get("navigation", {})
        assert "headingDegrees" not in navigation
        assert "status" not in navigation
        assert "speedOverGroundKnots" not in navigation

    def test_position_documents_do_not_duplicate_vessel_metadata(
        self, tmp_path: Path, test_database: Database[dict[str, Any]]
    ) -> None:
        """ADR-0002: metadata lives once per vessel, not on 5.9M documents."""
        source = write_ais_csv(tmp_path / "ais.csv", [ais_row(at=BASE)])
        run_ingest(source, test_database)

        document = test_database[collections.VESSEL_POSITIONS].find_one({})
        assert document is not None
        for absent in ("name", "vessel_name", "imo", "callSign", "dimensions", "vesselType"):
            assert absent not in document

        vessel = test_database[collections.VESSELS].find_one({"_id": "366000001"})
        assert vessel is not None
        assert vessel["name"] == "TEST VESSEL"
        assert vessel["nameNormalized"] == "TEST VESSEL"
        assert vessel["dimensions"] == {
            "lengthMeters": 100,
            "widthMeters": 20,
            "draftMeters": 5.0,
        }

    def test_vessel_activity_window_spans_all_observations(
        self, tmp_path: Path, test_database: Database[dict[str, Any]]
    ) -> None:
        source = write_ais_csv(
            tmp_path / "ais.csv",
            [
                ais_row(at=BASE + minutes(30), longitude=-72.0),
                ais_row(at=BASE, longitude=-74.0),
                ais_row(at=BASE + minutes(60), longitude=-70.0),
            ],
        )
        run_ingest(source, test_database)

        vessel = test_database[collections.VESSELS].find_one({"_id": "366000001"})
        assert vessel is not None
        assert vessel["firstSeenAt"] == BASE
        assert vessel["lastSeenAt"] == BASE + minutes(60)

    def test_blank_metadata_does_not_erase_a_known_value(
        self, tmp_path: Path, test_database: Database[dict[str, Any]]
    ) -> None:
        """Some broadcasts carry blanks; they must not wipe existing metadata."""
        source = write_ais_csv(
            tmp_path / "ais.csv",
            [
                ais_row(at=BASE, name="REAL NAME"),
                ais_row(
                    at=BASE + minutes(1),
                    vessel_name="",
                    call_sign="",
                    vessel_type="",
                ),
            ],
        )
        run_ingest(source, test_database)

        vessel = test_database[collections.VESSELS].find_one({"_id": "366000001"})
        assert vessel is not None
        assert vessel["name"] == "REAL NAME"


class TestDryRun:
    def test_dry_run_parses_and_counts_but_writes_nothing(
        self, tmp_path: Path, test_database: Database[dict[str, Any]]
    ) -> None:
        source = write_ais_csv(
            tmp_path / "ais.csv",
            [ais_row(at=BASE + minutes(i), longitude=-74.0 + i * 0.01) for i in range(20)],
        )
        stats = run_ingest(source, test_database, dry_run=True)

        assert stats.rows_read == 20
        assert stats.rows_valid == 20
        assert stats.positions_inserted == 0
        assert test_database[collections.VESSEL_POSITIONS].count_documents({}) == 0
        assert test_database[collections.VESSELS].count_documents({}) == 0
