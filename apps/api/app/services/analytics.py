"""Aggregation pipelines behind the analytics screens.

Rules applied throughout:

* Every pipeline that touches ``vessel_positions`` starts with a ``$match`` on
  an indexed field, so nothing begins with a full collection scan.
* Distributions that describe *vessels* run against ``vessel_latest`` (16,294
  documents) rather than ``vessel_positions`` (5.9M). The response states which
  basis was used, because "how many cargo vessels" and "how many cargo vessel
  observations" are different questions and conflating them would be misleading.
* Results are bounded.
* Three of these — traffic, speed, and most-active — aggregate the whole
  archive when asked for the whole archive, which no index can make selective.
  They consult :mod:`app.services.rollup` first and fall through to the live
  pipeline when it cannot be proven to answer the request. The measurement that
  motivated it, and the covering index that was tried and rejected, are
  recorded in that module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pymongo.asynchronous.database import AsyncDatabase

from app.api import schemas
from app.db import collections
from app.domain.vessel_types import describe_vessel_type
from app.services import mappers, rollup

#: Buckets in knots. Chosen to separate operationally distinct regimes rather
#: than as even intervals: the profiled data has 3,828,946 observations at
#: exactly 0 knots, so a linear histogram would be one enormous bar.
SPEED_BUCKETS: tuple[tuple[str, float, float | None], ...] = (
    ("Stopped (0)", 0.0, 0.0),
    ("Drifting (0-1)", 0.0, 1.0),
    ("Manoeuvring (1-5)", 1.0, 5.0),
    ("Slow transit (5-10)", 5.0, 10.0),
    ("Transit (10-15)", 10.0, 15.0),
    ("Fast transit (15-20)", 15.0, 20.0),
    ("High speed (20+)", 20.0, None),
)


async def traffic_over_time(
    database: AsyncDatabase[dict[str, Any]],
    *,
    start: datetime,
    end: datetime,
    interval: Literal["hour", "15min"] = "hour",
) -> schemas.TrafficResponse:
    """Observation counts bucketed over time.

    ``$dateTrunc`` does the bucketing in the database, so no raw timestamps
    cross the wire. ``distinct_vessels`` uses ``$addToSet`` on MMSI, which is
    bounded here because a single day has at most 16,294 distinct vessels.
    """
    kind = rollup.TRAFFIC_HOUR if interval == "hour" else rollup.TRAFFIC_15MIN
    precomputed = await rollup.load(database, kind, start=start, end=end)
    if precomputed is not None:
        buckets = [
            schemas.TimeBucket(
                bucket=entry["bucket"],
                observations=entry["observations"],
                distinct_vessels=entry["distinctVessels"],
            )
            for entry in precomputed["payload"]["buckets"]
        ]
        return schemas.TrafficResponse(
            buckets=buckets,
            interval=interval,
            start=start,
            end=end,
            total_observations=sum(bucket.observations for bucket in buckets),
            computed_at=precomputed["computedAt"],
        )

    unit, bin_size = ("hour", 1) if interval == "hour" else ("minute", 15)
    pipeline: list[dict[str, Any]] = [
        {"$match": {"timestamp": {"$gte": start, "$lte": end}}},
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

    buckets = [
        schemas.TimeBucket(
            bucket=document["_id"],
            observations=document["observations"],
            distinct_vessels=document["distinctVessels"],
        )
        async for document in await database[collections.VESSEL_POSITIONS].aggregate(pipeline)
    ]
    return schemas.TrafficResponse(
        buckets=buckets,
        interval=interval,
        start=start,
        end=end,
        total_observations=sum(bucket.observations for bucket in buckets),
    )


async def vessel_type_distribution(
    database: AsyncDatabase[dict[str, Any]],
) -> schemas.DistributionResponse:
    """How many *vessels* of each type family are in the dataset.

    Runs over ``vessel_latest``, so this counts vessels — not observations.
    Counting observations would over-represent frequently-broadcasting vessels
    such as ferries, which dominate the raw row counts.
    """
    pipeline: list[dict[str, Any]] = [
        {"$group": {"_id": "$vesselType", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    families: dict[str, int] = {}
    total = 0
    async for document in await database[collections.VESSEL_LATEST].aggregate(pipeline):
        family = describe_vessel_type(document["_id"]).family
        families[family] = families.get(family, 0) + document["count"]
        total += document["count"]

    categories = [
        schemas.CategoryCount(key=family, label=family, count=count)
        for family, count in sorted(families.items(), key=lambda item: -item[1])
    ]
    return schemas.DistributionResponse(
        categories=categories, total=total, basis="vessels (vessel_latest)"
    )


async def transceiver_distribution(
    database: AsyncDatabase[dict[str, Any]],
) -> schemas.DistributionResponse:
    """Split of Class A vs Class B transceivers, by vessel.

    Class A is carried by larger commercial vessels; Class B by smaller craft.
    The split is a useful proxy for fleet composition.
    """
    pipeline: list[dict[str, Any]] = [
        {"$group": {"_id": "$transceiverClass", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    categories: list[schemas.CategoryCount] = []
    total = 0
    async for document in await database[collections.VESSEL_LATEST].aggregate(pipeline):
        key = document["_id"] or "unknown"
        label = {"A": "Class A", "B": "Class B"}.get(key, "Not reported")
        categories.append(schemas.CategoryCount(key=key, label=label, count=document["count"]))
        total += document["count"]
    return schemas.DistributionResponse(
        categories=categories, total=total, basis="vessels (vessel_latest)"
    )


async def speed_distribution(
    database: AsyncDatabase[dict[str, Any]],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> schemas.SpeedDistributionResponse:
    """Histogram of reported speed over ground across observations.

    ``$bucket`` with explicit boundaries rather than ``$bucketAuto``: the
    boundaries carry operational meaning (stopped, manoeuvring, transit) that an
    automatic split would destroy.
    """
    labels = [
        ("Stopped or drifting (0-0.5)", 0.0, 0.5),
        ("Very slow (0.5-1)", 0.5, 1.0),
        ("Manoeuvring (1-5)", 1.0, 5.0),
        ("Slow transit (5-10)", 5.0, 10.0),
        ("Transit (10-15)", 10.0, 15.0),
        ("Fast transit (15-20)", 15.0, 20.0),
        ("High speed (20+)", 20.0, None),
    ]
    note = (
        "Counts observations, not vessels. A stationary vessel broadcasting all "
        "day contributes many observations to the lowest bucket."
    )

    precomputed = await rollup.load(database, rollup.SPEED, start=start, end=end)
    if precomputed is not None:
        stored: dict[str, int] = precomputed["payload"]["counts"]
        buckets = [
            schemas.SpeedBucket(
                label=label,
                lower_knots=lower,
                upper_knots=upper,
                count=stored.get(str(lower), 0),
            )
            for label, lower, upper in labels
        ]
        return schemas.SpeedDistributionResponse(
            buckets=buckets,
            total=sum(bucket.count for bucket in buckets),
            note=note,
            computed_at=precomputed["computedAt"],
        )

    match: dict[str, Any] = {"navigation.speedOverGroundKnots": {"$exists": True}}
    if start is not None or end is not None:
        window: dict[str, Any] = {}
        if start is not None:
            window["$gte"] = start
        if end is not None:
            window["$lte"] = end
        match["timestamp"] = window

    boundaries = list(rollup.SPEED_BOUNDARIES)
    pipeline: list[dict[str, Any]] = [
        {"$match": match},
        {
            "$bucket": {
                "groupBy": "$navigation.speedOverGroundKnots",
                "boundaries": boundaries,
                "default": "other",
                "output": {"count": {"$sum": 1}},
            }
        },
    ]

    counts: dict[float, int] = {
        float(document["_id"]): document["count"]
        async for document in await database[collections.VESSEL_POSITIONS].aggregate(pipeline)
        if isinstance(document["_id"], int | float)
    }
    total = sum(counts.values())

    buckets = [
        schemas.SpeedBucket(
            label=label, lower_knots=lower, upper_knots=upper, count=counts.get(lower, 0)
        )
        for label, lower, upper in labels
    ]
    return schemas.SpeedDistributionResponse(buckets=buckets, total=total, note=note)


async def most_active_vessels(
    database: AsyncDatabase[dict[str, Any]],
    *,
    start: datetime,
    end: datetime,
    limit: int = 20,
) -> list[schemas.ActiveVessel]:
    """Vessels with the most observations in a window.

    "Most active" means *most frequently broadcasting*, which correlates with
    time underway but is not the same thing — the endpoint documentation says
    so rather than implying a distance-travelled ranking.
    """
    # The rollup stores a fixed depth. A request deeper than that is answered
    # live rather than silently truncated.
    if limit <= rollup.ACTIVE_VESSELS_DEPTH:
        precomputed = await rollup.load(database, rollup.ACTIVE_VESSELS, start=start, end=end)
        if precomputed is not None:
            ranked = precomputed["payload"]["vessels"][:limit]
            identities = {
                document["_id"]: document
                async for document in database[collections.VESSELS].find(
                    {"_id": {"$in": [entry["mmsi"] for entry in ranked]}}
                )
            }
            return [
                schemas.ActiveVessel(
                    vessel=mappers.to_vessel_summary(
                        identities.get(entry["mmsi"], {"_id": entry["mmsi"]})
                    ),
                    observations=entry["observations"],
                )
                for entry in ranked
            ]

    pipeline: list[dict[str, Any]] = [
        {"$match": {"timestamp": {"$gte": start, "$lte": end}}},
        {"$group": {"_id": "$mmsi", "observations": {"$sum": 1}}},
        {"$sort": {"observations": -1}},
        {"$limit": limit},
        {
            "$lookup": {
                "from": collections.VESSELS,
                "localField": "_id",
                "foreignField": "_id",
                "as": "vessel",
            }
        },
        {"$unwind": {"path": "$vessel", "preserveNullAndEmptyArrays": True}},
    ]
    results: list[schemas.ActiveVessel] = []
    async for document in await database[collections.VESSEL_POSITIONS].aggregate(pipeline):
        vessel = document.get("vessel") or {"_id": document["_id"]}
        results.append(
            schemas.ActiveVessel(
                vessel=mappers.to_vessel_summary(vessel),
                observations=document["observations"],
            )
        )
    return results


async def navigation_status_distribution(
    database: AsyncDatabase[dict[str, Any]],
) -> schemas.DistributionResponse:
    """Reported navigational status across current vessel state."""
    from app.domain.vessel_types import describe_nav_status

    pipeline: list[dict[str, Any]] = [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]
    categories: list[schemas.CategoryCount] = []
    total = 0
    async for document in await database[collections.VESSEL_LATEST].aggregate(pipeline):
        code = document["_id"]
        categories.append(
            schemas.CategoryCount(
                key=str(code) if code is not None else "unknown",
                label=describe_nav_status(code),
                count=document["count"],
            )
        )
        total += document["count"]
    return schemas.DistributionResponse(
        categories=categories, total=total, basis="vessels (vessel_latest)"
    )
