"""Ingestion run lifecycle and post-import validation.

An ingestion run is a first-class record, not a log line. It carries the source
identity, the checkpoint needed to resume, and the counters used to reconcile
what was stored against what the profiler said was in the file.

SOUL.md §6: *counts reported after import must reconcile against the profiler;
an unexplained discrepancy is a bug, not a rounding detail.* That reconciliation
is implemented in :func:`validate_import`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from bson import ObjectId
from pymongo.database import Database

from app.db import collections, indexes
from app.ingest.pipeline import SCHEMA_VERSION, IngestionStats

RunStatus = Literal["running", "completed", "failed", "cancelled"]


def start_run(
    database: Database[dict[str, Any]],
    *,
    path: Path,
    checksum: str,
    dataset: str,
    batch_size: int,
    limit: int | None,
    resume_from_row: int,
    dry_run: bool,
) -> ObjectId:
    """Create an ``ingestion_runs`` document and return its id."""
    document: dict[str, Any] = {
        "sourceFile": path.name,
        "sourcePath": str(path),
        "sourceBytes": path.stat().st_size,
        "sourceChecksum": checksum,
        "dataset": dataset,
        "schemaVersion": SCHEMA_VERSION,
        "startedAt": datetime.now(UTC),
        "completedAt": None,
        "status": "running",
        "lastCheckpointRow": resume_from_row,
        "options": {
            "batchSize": batch_size,
            "limit": limit,
            "resumeFromRow": resume_from_row,
            "dryRun": dry_run,
        },
        "stats": {},
        "error": None,
    }
    result = database[collections.INGESTION_RUNS].insert_one(document)
    inserted_id = result.inserted_id
    # Narrows the driver's Any return type; insert_one always yields an ObjectId here.
    assert isinstance(inserted_id, ObjectId)
    return inserted_id


def finish_run(
    database: Database[dict[str, Any]],
    run_id: ObjectId,
    *,
    status: RunStatus,
    stats: IngestionStats,
    error: str | None = None,
) -> None:
    """Close out a run with its final counters."""
    database[collections.INGESTION_RUNS].update_one(
        {"_id": run_id},
        {
            "$set": {
                "status": status,
                "completedAt": datetime.now(UTC),
                "stats": stats.as_document(),
                "lastCheckpointRow": stats.rows_read,
                "error": error,
            }
        },
    )


def find_resume_point(
    database: Database[dict[str, Any]], *, checksum: str
) -> tuple[int, ObjectId] | None:
    """Find the checkpoint of the most recent incomplete run for this file.

    Matching on the **checksum** rather than the filename means a resume cannot
    silently continue against different data that happens to share a name.
    """
    document = database[collections.INGESTION_RUNS].find_one(
        {"sourceChecksum": checksum, "status": {"$in": ["running", "cancelled", "failed"]}},
        sort=[("startedAt", -1)],
    )
    if document is None:
        return None
    checkpoint = int(document.get("lastCheckpointRow", 0))
    return checkpoint, document["_id"]


def latest_run(database: Database[dict[str, Any]]) -> dict[str, Any] | None:
    """Most recent ingestion run, for `navisight-data status` and the API."""
    return database[collections.INGESTION_RUNS].find_one(sort=[("startedAt", -1)])


def validate_import(
    database: Database[dict[str, Any]],
    *,
    expected_rows: int | None = None,
    expected_duplicates: int | None = None,
) -> dict[str, Any]:
    """Check stored data for internal consistency and against the profiler.

    Returns a report with a ``checks`` list; each check has ``ok`` and a human
    explanation. The caller exits non-zero if any check fails, so an import that
    lost data cannot be reported as successful.
    """
    positions = database[collections.VESSEL_POSITIONS]
    vessels = database[collections.VESSELS]
    latest = database[collections.VESSEL_LATEST]

    position_count = positions.estimated_document_count()
    exact_position_count = positions.count_documents({})
    vessel_count = vessels.count_documents({})
    latest_count = latest.count_documents({})

    distinct_mmsi_in_latest = latest_count  # _id is the MMSI, so this is exact.

    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    # --- Reconciliation against the profiler ------------------------------
    if expected_rows is not None:
        duplicates = expected_duplicates or 0
        expected_stored = expected_rows - duplicates
        ok = exact_position_count == expected_stored
        check(
            "position_count_reconciles_with_profile",
            ok,
            (
                f"Profiler read {expected_rows:,} rows with {duplicates:,} exact duplicates, "
                f"so {expected_stored:,} documents were expected; "
                f"{exact_position_count:,} are stored."
                + ("" if ok else "  MISMATCH — investigate before trusting this import.")
            ),
        )

    # --- Referential consistency ------------------------------------------
    check(
        "every_latest_vessel_has_a_vessel_document",
        latest_count <= vessel_count,
        f"vessel_latest has {latest_count:,} documents; vessels has {vessel_count:,}.",
    )

    orphan = latest.aggregate(
        [
            {"$limit": 5000},
            {
                "$lookup": {
                    "from": collections.VESSELS,
                    "localField": "_id",
                    "foreignField": "_id",
                    "as": "vessel",
                }
            },
            {"$match": {"vessel": {"$size": 0}}},
            {"$count": "orphans"},
        ]
    )
    orphan_count = next(iter(orphan), {}).get("orphans", 0)
    check(
        "no_orphaned_latest_state",
        orphan_count == 0,
        f"{orphan_count} of the first 5,000 vessel_latest documents lack a vessels document.",
    )

    # --- Geometry ----------------------------------------------------------
    bad_geometry = positions.count_documents(
        {
            "$or": [
                {"location.type": {"$ne": "Point"}},
                {"location.coordinates.0": {"$lt": -180}},
                {"location.coordinates.0": {"$gt": 180}},
                {"location.coordinates.1": {"$lt": -90}},
                {"location.coordinates.1": {"$gt": 90}},
            ]
        },
        limit=1,
    )
    check(
        "all_positions_have_valid_geojson",
        bad_geometry == 0,
        "No position document has a malformed or out-of-range GeoJSON Point."
        if bad_geometry == 0
        else "Found position documents with invalid geometry.",
    )

    # --- Time --------------------------------------------------------------
    bounds = list(
        positions.aggregate(
            [
                {
                    "$group": {
                        "_id": None,
                        "min": {"$min": "$timestamp"},
                        "max": {"$max": "$timestamp"},
                    }
                }
            ]
        )
    )
    time_range = bounds[0] if bounds else {"min": None, "max": None}
    check(
        "timestamp_range_is_populated",
        time_range["min"] is not None,
        f"Stored observations span {time_range['min']} to {time_range['max']}.",
    )

    # --- Indexes -----------------------------------------------------------
    missing: list[str] = []
    for spec in indexes.INDEX_SPECS:
        if spec.collection == collections.PORTS:
            continue  # optional dataset
        existing = set(database[spec.collection].index_information())
        if spec.name not in existing:
            missing.append(f"{spec.collection}.{spec.name}")
    check(
        "declared_indexes_exist",
        not missing,
        "All declared indexes are present." if not missing else f"Missing: {', '.join(missing)}",
    )

    return {
        "counts": {
            "vessel_positions": exact_position_count,
            "vessel_positions_estimated": position_count,
            "vessels": vessel_count,
            "vessel_latest": distinct_mmsi_in_latest,
        },
        "timeRange": {
            "min": time_range["min"].isoformat() if time_range["min"] else None,
            "max": time_range["max"].isoformat() if time_range["max"] else None,
        },
        "checks": checks,
        "ok": all(item["ok"] for item in checks),
    }
