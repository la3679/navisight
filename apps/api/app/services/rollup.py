"""Precomputed whole-archive analytics.

Measured problem
----------------

The analytics page asks three questions of ``vessel_positions`` — traffic per
bucket, the speed histogram, and the busiest vessels — over the *entire*
imported window. Each is a full aggregation across 5,928,519 documents, and on
this machine they measured **43.6 s, 38.4 s, and 31.8 s**.

``explain()`` showed why. The traffic pipeline already uses
``position_timestamp``, but ``$mmsi`` is not in that index, so every one of the
5.9M matched keys is followed by a document fetch. A covering index on
``(timestamp, mmsi, navigation.speedOverGroundKnots)`` removed the fetches
entirely — ``docsExamined`` 0 — and brought traffic to **20.1 s**. Better, and
still far too slow for a page load, at a cost of 156 MiB and a minute of index
build. That index was measured and rejected.

The reason no index fixes this is that the query is not selective: the window
*is* the dataset, so any plan must visit every record.

Decision
--------

Compute these once and store the answers. The archive is immutable after
import — a whole-day aggregate cannot change between page loads, so
recomputing it per request is pure waste (SOUL.md §5: optimize against a
measurement; §13: cache only after a measurement shows it is needed. Both
conditions are met, and the numbers above are the measurement).

The rollup holds exact counts, not samples or estimates. It is the same
aggregation, run once.

Staleness
---------

A cache that can silently serve the wrong answer is worse than a slow query, so
serving a rollup is gated on two conditions, both cheap:

1. **The request must cover the whole archive.** A rollup computed over
   ``[coverage_start, coverage_end]`` answers any request whose window contains
   that range, because no observation exists outside it. A narrower request
   falls through to the live aggregation.
2. **The collection must not have changed.** Each rollup records the document
   count it was computed from; if the collection's count differs, the rollup is
   stale and is ignored.

Anything that does not satisfy both runs live and is correct but slow. There is
no path here that returns an outdated number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pymongo import ReplaceOne
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.database import Database

from app.db import collections

#: Rollup kinds. The value is the document ``_id``, so it is also the key.
TRAFFIC_HOUR = "traffic:hour"
TRAFFIC_15MIN = "traffic:15min"
SPEED = "speed"
ACTIVE_VESSELS = "active-vessels"

#: How many vessels the active-vessels rollup stores. Requests for more than
#: this fall through to the live aggregation rather than being silently capped.
ACTIVE_VESSELS_DEPTH = 50

ALL_KINDS: tuple[str, ...] = (TRAFFIC_HOUR, TRAFFIC_15MIN, SPEED, ACTIVE_VESSELS)


@dataclass(frozen=True)
class RollupWindow:
    """The archive extent a set of rollups was computed over."""

    start: datetime
    end: datetime
    document_count: int


def _covers(rollup: dict[str, Any], *, start: datetime | None, end: datetime | None) -> bool:
    """Whether a request window contains everything this rollup summarises."""
    if start is not None and start > rollup["coverageStart"]:
        return False
    return not (end is not None and end < rollup["coverageEnd"])


async def load(
    database: AsyncDatabase[dict[str, Any]],
    kind: str,
    *,
    start: datetime | None,
    end: datetime | None,
) -> dict[str, Any] | None:
    """Return a usable rollup payload, or ``None`` to compute live.

    ``None`` is returned whenever the rollup cannot be *proven* to answer the
    request: it is missing, the collection has changed under it, or the window
    asked for is narrower than the archive.
    """
    document = await database[collections.ANALYTICS_ROLLUP].find_one({"_id": kind})
    if document is None:
        return None
    if not _covers(document, start=start, end=end):
        return None

    # Cheap metadata read, not a count_documents() scan.
    current = await database[collections.VESSEL_POSITIONS].estimated_document_count()
    if current != document["sourceDocumentCount"]:
        return None

    return document


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------
def _window(database: Database[dict[str, Any]]) -> RollupWindow | None:
    """The archive's extent, from the data rather than from configuration."""
    positions = database[collections.VESSEL_POSITIONS]
    first = positions.find_one({}, sort=[("timestamp", 1)], projection={"timestamp": 1})
    last = positions.find_one({}, sort=[("timestamp", -1)], projection={"timestamp": 1})
    if first is None or last is None:
        return None
    return RollupWindow(
        start=first["timestamp"],
        end=last["timestamp"],
        document_count=positions.estimated_document_count(),
    )


def _traffic(
    database: Database[dict[str, Any]], window: RollupWindow, *, unit: str, bin_size: int
) -> list[dict[str, Any]]:
    pipeline: list[dict[str, Any]] = [
        {"$match": {"timestamp": {"$gte": window.start, "$lte": window.end}}},
        {
            "$group": {
                "_id": {"$dateTrunc": {"date": "$timestamp", "unit": unit, "binSize": bin_size}},
                "observations": {"$sum": 1},
                "vessels": {"$addToSet": "$mmsi"},
            }
        },
        {
            "$project": {
                "_id": 1,
                "observations": 1,
                "distinctVessels": {"$size": "$vessels"},
            }
        },
        {"$sort": {"_id": 1}},
    ]
    return [
        {
            "bucket": document["_id"],
            "observations": document["observations"],
            "distinctVessels": document["distinctVessels"],
        }
        for document in database[collections.VESSEL_POSITIONS].aggregate(
            pipeline, allowDiskUse=True
        )
    ]


#: Boundaries duplicated from the live pipeline would drift; they live here and
#: the live pipeline imports them.
SPEED_BOUNDARIES: tuple[float, ...] = (0.0, 0.5, 1.0, 5.0, 10.0, 15.0, 20.0, 1_000.0)


def _speed(database: Database[dict[str, Any]], window: RollupWindow) -> dict[str, int]:
    pipeline: list[dict[str, Any]] = [
        {
            "$match": {
                "navigation.speedOverGroundKnots": {"$exists": True},
                "timestamp": {"$gte": window.start, "$lte": window.end},
            }
        },
        {
            "$bucket": {
                "groupBy": "$navigation.speedOverGroundKnots",
                "boundaries": list(SPEED_BOUNDARIES),
                "default": "other",
                "output": {"count": {"$sum": 1}},
            }
        },
    ]
    return {
        # Keys are stringified because BSON document keys must be strings.
        str(float(document["_id"])): document["count"]
        for document in database[collections.VESSEL_POSITIONS].aggregate(
            pipeline, allowDiskUse=True
        )
        if isinstance(document["_id"], int | float)
    }


def _active_vessels(
    database: Database[dict[str, Any]], window: RollupWindow
) -> list[dict[str, Any]]:
    pipeline: list[dict[str, Any]] = [
        {"$match": {"timestamp": {"$gte": window.start, "$lte": window.end}}},
        {"$group": {"_id": "$mmsi", "observations": {"$sum": 1}}},
        {"$sort": {"observations": -1}},
        {"$limit": ACTIVE_VESSELS_DEPTH},
    ]
    return [
        {"mmsi": document["_id"], "observations": document["observations"]}
        for document in database[collections.VESSEL_POSITIONS].aggregate(
            pipeline, allowDiskUse=True
        )
    ]


def build(database: Database[dict[str, Any]]) -> dict[str, Any]:
    """Recompute every rollup. Synchronous: this is CLI-side batch work.

    Returns a summary suitable for printing, including the wall time each
    aggregation took — those are the numbers the decision above rests on, so
    they are re-measurable rather than quoted from a comment.
    """
    from time import perf_counter

    window = _window(database)
    if window is None:
        return {"built": 0, "reason": "no positions imported"}

    computed_at = datetime.now(UTC)
    timings: dict[str, float] = {}

    def timed(kind: str, produce: Any) -> Any:
        started = perf_counter()
        payload = produce()
        timings[kind] = round(perf_counter() - started, 2)
        return payload

    payloads: dict[str, Any] = {
        TRAFFIC_HOUR: timed(
            TRAFFIC_HOUR, lambda: {"buckets": _traffic(database, window, unit="hour", bin_size=1)}
        ),
        TRAFFIC_15MIN: timed(
            TRAFFIC_15MIN,
            lambda: {"buckets": _traffic(database, window, unit="minute", bin_size=15)},
        ),
        SPEED: timed(SPEED, lambda: {"counts": _speed(database, window)}),
        ACTIVE_VESSELS: timed(
            ACTIVE_VESSELS, lambda: {"vessels": _active_vessels(database, window)}
        ),
    }

    operations = [
        ReplaceOne(
            {"_id": kind},
            {
                "_id": kind,
                "coverageStart": window.start,
                "coverageEnd": window.end,
                "sourceDocumentCount": window.document_count,
                "computedAt": computed_at,
                "computeSeconds": timings[kind],
                "payload": payload,
            },
            upsert=True,
        )
        for kind, payload in payloads.items()
    ]
    database[collections.ANALYTICS_ROLLUP].bulk_write(operations, ordered=False)

    return {
        "built": len(operations),
        "coverageStart": window.start,
        "coverageEnd": window.end,
        "sourceDocumentCount": window.document_count,
        "computedAt": computed_at,
        "seconds": timings,
    }
