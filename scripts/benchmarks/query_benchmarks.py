"""Measure what each index is actually worth, against the real imported data.

SOUL.md §7 says every index must serve a named query, and that an index nobody
can name a query for gets deleted. `app/db/indexes.py` names the query for each
one. This script measures whether the name is *true* — an index justified by a
plausible sentence and no number is exactly the thing that rule exists to
prevent.

## Method

Each query is run two ways against the same collection, same process, same warm
cache:

- **as planned** — MongoDB picks the index;
- **forced scan** — the same query with ``hint({"$natural": 1})``.

Hinting a natural scan is deliberate. The alternative, dropping the index and
rebuilding it, takes minutes on 5.9M documents, changes the collection between
the two measurements, and risks leaving a development database without an index
if the script dies halfway. A hinted scan measures the same thing — what this
query costs when the index cannot be used — without touching anything.

Every query is run ``REPEATS`` times and the **median** is reported. Not the
minimum, which flatters, and not the mean, which one slow run distorts.

``explain()`` output is captured alongside each timing, because the timing alone
does not tell you *why*: ``totalKeysExamined`` and ``totalDocsExamined`` are
what distinguish "the index was used" from "the index existed".

## Usage

    cd apps/api
    uv run python ../../scripts/benchmarks/query_benchmarks.py
    uv run python ../../scripts/benchmarks/query_benchmarks.py --json out.json

Reads ``MONGODB_URI`` and ``MONGODB_DATABASE``. Read-only: it creates nothing,
drops nothing, and writes nothing to the database.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.config import get_settings  # noqa: E402
from app.db import collections  # noqa: E402
from pymongo import ASCENDING, DESCENDING, MongoClient  # noqa: E402
from pymongo.database import Database  # noqa: E402

#: Enough to see past a single unlucky run without making the script a chore.
REPEATS = 5

#: A natural scan of 5.9M documents is slow. Run those fewer times.
SCAN_REPEATS = 3

NATURAL: dict[str, Any] = {"$natural": 1}


def _median_ms(operation: Callable[[], Any], repeats: int) -> float:
    timings: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter()
        operation()
        timings.append((time.perf_counter() - started) * 1000)
    return round(statistics.median(timings), 2)


def _explain_stats(explained: dict[str, Any]) -> dict[str, Any]:
    stats = explained.get("executionStats", {})
    return {
        "nReturned": stats.get("nReturned"),
        "totalKeysExamined": stats.get("totalKeysExamined"),
        "totalDocsExamined": stats.get("totalDocsExamined"),
        "executionTimeMillis": stats.get("executionTimeMillis"),
    }


def _sample_mmsi(database: Database[dict[str, Any]]) -> str:
    document = database[collections.VESSEL_LATEST].find_one({}, {"_id": 1})
    if document is None:
        raise SystemExit("No data. Import the archive before benchmarking.")
    return str(document["_id"])


def _coverage(database: Database[dict[str, Any]]) -> tuple[datetime, datetime]:
    positions = database[collections.VESSEL_POSITIONS]
    first = positions.find_one({}, {"timestamp": 1}, sort=[("timestamp", ASCENDING)])
    last = positions.find_one({}, {"timestamp": 1}, sort=[("timestamp", DESCENDING)])
    if first is None or last is None:
        raise SystemExit("No data. Import the archive before benchmarking.")
    return first["timestamp"], last["timestamp"]


def run(database: Database[dict[str, Any]]) -> list[dict[str, Any]]:
    positions = database[collections.VESSEL_POSITIONS]
    latest = database[collections.VESSEL_LATEST]
    vessels = database[collections.VESSELS]

    mmsi = _sample_mmsi(database)
    start, end = _coverage(database)
    # A one-hour window in the middle of the archive: the case the timestamp
    # index exists for, and the one a whole-archive query does not exercise.
    window_start = start + (end - start) / 2
    window_end = window_start + timedelta(hours=1)

    results: list[dict[str, Any]] = []

    # ---------------------------------------------------------------- track
    def track_indexed() -> None:
        list(positions.find({"mmsi": mmsi}).sort([("timestamp", DESCENDING)]).limit(5_000))

    def track_scan() -> None:
        list(
            positions.find({"mmsi": mmsi})
            .hint(NATURAL)
            .sort([("timestamp", DESCENDING)])
            .limit(5_000)
        )

    results.append(
        {
            "name": "One vessel's track",
            "query": f"vessel_positions.find({{mmsi}}).sort(timestamp desc).limit(5000)",
            "serves": "GET /api/v1/vessels/{mmsi}/positions and /track",
            "index": "position_mmsi_timestamp",
            "indexedMs": _median_ms(track_indexed, REPEATS),
            "scanMs": _median_ms(track_scan, SCAN_REPEATS),
            "explainIndexed": _explain_stats(
                positions.find({"mmsi": mmsi})
                .sort([("timestamp", DESCENDING)])
                .limit(5_000)
                .explain()
            ),
        }
    )

    # --------------------------------------------------------- time window
    window = {"timestamp": {"$gte": window_start, "$lte": window_end}}

    def window_indexed() -> None:
        positions.count_documents(window)

    def window_scan() -> None:
        positions.count_documents(window, hint=NATURAL)

    results.append(
        {
            "name": "One-hour window across all vessels",
            "query": "vessel_positions.count({timestamp: {$gte, $lte}})",
            "serves": "sub-day /api/v1/analytics/* (the rollup covers whole-archive)",
            "index": "position_timestamp",
            "indexedMs": _median_ms(window_indexed, REPEATS),
            "scanMs": _median_ms(window_scan, SCAN_REPEATS),
            "explainIndexed": _explain_stats(positions.find(window).explain()),
        }
    )

    # ------------------------------------------------------- map viewport
    viewport = {
        "location": {
            "$geoWithin": {
                "$box": [[-74.5, 40.3], [-73.5, 41.0]],
            }
        }
    }

    def viewport_indexed() -> None:
        list(latest.find(viewport).limit(5_000))

    def viewport_scan() -> None:
        # $geoWithin/$box is one of the few geo predicates that runs without a
        # geo index, which is what makes this comparison possible at all.
        list(latest.find(viewport).hint(NATURAL).limit(5_000))

    results.append(
        {
            "name": "Map viewport",
            "query": "vessel_latest.find({location: {$geoWithin: {$box}}}).limit(5000)",
            "serves": "GET /api/v1/map/vessels — runs on every map pan",
            "index": "latest_location_2dsphere",
            "indexedMs": _median_ms(viewport_indexed, REPEATS),
            "scanMs": _median_ms(viewport_scan, REPEATS),
            "explainIndexed": _explain_stats(latest.find(viewport).limit(5_000).explain()),
        }
    )

    # --------------------------------------------- the polygon alternative
    # Same rectangle expressed as GeoJSON, which the 2dsphere index CAN serve.
    # Measured rather than assumed, because it is the obvious "fix" for the
    # COLLSCAN above and its semantics are not identical.
    polygon = {
        "location": {
            "$geoWithin": {
                "$geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-74.5, 40.3],
                            [-73.5, 40.3],
                            [-73.5, 41.0],
                            [-74.5, 41.0],
                            [-74.5, 40.3],
                        ]
                    ],
                }
            }
        }
    }

    results.append(
        {
            "name": "Map viewport as a GeoJSON polygon",
            "query": "vessel_latest.find({location: {$geoWithin: {$geometry: Polygon}}})",
            "serves": "nothing today — the indexable alternative to $box, measured",
            "index": "latest_location_2dsphere",
            "indexedMs": _median_ms(lambda: list(latest.find(polygon).limit(5_000)), REPEATS),
            "scanMs": None,
            "explainIndexed": _explain_stats(latest.find(polygon).limit(5_000).explain()),
            "matchedSameDocuments": (
                latest.count_documents(polygon) == latest.count_documents(viewport)
            ),
        }
    )

    # ---------------------------------------------------------- geoNear
    # The query that genuinely requires the geo index: MongoDB refuses to plan
    # $geoNear without one, so there is no scan to compare against.
    near_pipeline: list[dict[str, Any]] = [
        {
            "$geoNear": {
                "near": {"type": "Point", "coordinates": [-74.0, 40.6]},
                "distanceField": "distanceMeters",
                "maxDistance": 50_000,
                "spherical": True,
            }
        },
        {"$limit": 200},
    ]

    results.append(
        {
            "name": "Distance-sorted proximity ($geoNear)",
            "query": "vessel_latest.aggregate([$geoNear {50 km}, $limit 200])",
            "serves": "GET /api/v1/geo/nearby and the agent's find_vessels_near_location",
            "index": "latest_location_2dsphere",
            "indexedMs": _median_ms(lambda: list(latest.aggregate(near_pipeline)), REPEATS),
            "scanMs": None,
            "explainIndexed": {"note": "$geoNear cannot be planned without a geo index"},
        }
    )

    # ------------------------------------------- viewport over raw history
    # The query ADR-0003 exists to avoid: the same question asked of the full
    # position history instead of the materialized latest state.
    def viewport_over_positions() -> None:
        list(positions.find(viewport).limit(5_000))

    results.append(
        {
            "name": "Same viewport, over full position history",
            "query": "vessel_positions.find({location: {$geoWithin: {$box}}}).limit(5000)",
            "serves": "nothing — this is the shape ADR-0003 exists to avoid",
            "index": "position_location_2dsphere",
            "indexedMs": _median_ms(viewport_over_positions, REPEATS),
            "scanMs": None,
            "explainIndexed": _explain_stats(positions.find(viewport).limit(5_000).explain()),
        }
    )

    # ------------------------------------------------------ name prefix
    prefix = {"nameNormalized": {"$regex": "^A"}}

    def name_indexed() -> None:
        list(vessels.find(prefix).limit(50))

    def name_scan() -> None:
        list(vessels.find(prefix).hint(NATURAL).limit(50))

    results.append(
        {
            "name": "Vessel name prefix search",
            "query": "vessels.find({nameNormalized: /^A/}).limit(50)",
            "serves": "GET /api/v1/vessels?q= and the agent's find_vessel tool",
            "index": "vessel_name_normalized",
            "indexedMs": _median_ms(name_indexed, REPEATS),
            "scanMs": _median_ms(name_scan, REPEATS),
            "explainIndexed": _explain_stats(vessels.find(prefix).limit(50).explain()),
        }
    )

    # -------------------------------------------------- coverage bounds
    def bounds_sorted() -> None:
        positions.find_one({}, {"timestamp": 1}, sort=[("timestamp", ASCENDING)])
        positions.find_one({}, {"timestamp": 1}, sort=[("timestamp", DESCENDING)])

    def bounds_group() -> None:
        list(
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

    results.append(
        {
            "name": "Archive coverage bounds",
            "query": "two find_one(sort=timestamp) vs one $group $min/$max",
            "serves": "GET /api/v1/dataset/status — the header badge, on every page",
            "index": "position_timestamp",
            "indexedMs": _median_ms(bounds_sorted, REPEATS),
            "scanMs": _median_ms(bounds_group, SCAN_REPEATS),
            "explainIndexed": _explain_stats(
                positions.find({}, {"timestamp": 1}).sort([("timestamp", ASCENDING)]).limit(1).explain()
            ),
        }
    )

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="Also write raw results here.")
    arguments = parser.parse_args()

    settings = get_settings()
    client: MongoClient[dict[str, Any]] = MongoClient(settings.mongodb_uri, tz_aware=True)
    database = client[settings.mongodb_database]

    positions = database[collections.VESSEL_POSITIONS].estimated_document_count()
    if not positions:
        raise SystemExit(f"'{settings.mongodb_database}' holds no positions.")

    print(f"{settings.mongodb_database} @ {settings.mongodb_uri}")
    print(f"{positions:,} position documents\n")

    results = run(database)

    header = f"{'Query':<42} {'indexed':>10} {'scan':>12} {'factor':>9}"
    print(header)
    print("-" * len(header))
    for result in results:
        scan = result["scanMs"]
        factor = f"{scan / result['indexedMs']:.0f}x" if scan else "—"
        print(
            f"{result['name']:<42} {result['indexedMs']:>9.2f}ms "
            f"{(f'{scan:.2f}ms' if scan else '—'):>12} {factor:>9}"
        )

    print("\nexplain() for the planned query:")
    for result in results:
        stats = result["explainIndexed"]
        if "nReturned" not in stats:
            print(f"  {result['name']:<42} {stats.get('note', '')}")
            continue
        print(
            f"  {result['name']:<42} returned={stats['nReturned']} "
            f"keys={stats['totalKeysExamined']} docs={stats['totalDocsExamined']}"
        )

    if arguments.json:
        arguments.json.write_text(
            json.dumps(
                {
                    "measuredAt": datetime.now(UTC).isoformat(),
                    "database": settings.mongodb_database,
                    "positionDocuments": positions,
                    "repeats": {"default": REPEATS, "scan": SCAN_REPEATS},
                    "results": results,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"\nWrote {arguments.json}")

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
