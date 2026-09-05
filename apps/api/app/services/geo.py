"""Geospatial queries: proximity search and map viewport loading.

Both operate on ``vessel_latest`` by default (16,294 documents) rather than
``vessel_positions`` (5.9M). That is the entire point of maintaining
materialized state — see ADR-0003.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from app.api import schemas
from app.db import collections
from app.domain.geo import MAX_RADIUS_KM, BoundingBox, km_to_nautical_miles
from app.domain.vessel_types import describe_vessel_type
from app.errors import ApiError, ErrorCode
from app.services import mappers

_MAP_FIELDS = {
    "mmsi": 1,
    "name": 1,
    "location": 1,
    "timestamp": 1,
    "headingDegrees": 1,
    "courseOverGroundDegrees": 1,
    "speedOverGroundKnots": 1,
    "vesselType": 1,
}

#: Above this viewport area (square degrees) individual vessels are replaced by
#: aggregated cells. A continent-scale view would otherwise ship tens of
#: thousands of points to the browser for no readable benefit (SOUL.md §13).
CLUSTER_AREA_THRESHOLD_DEG2 = 60.0


def _vessel_filters(
    vessel_type: int | None,
    family: str | None,
    transceiver: str | None,
    min_speed: float | None,
    max_speed: float | None,
) -> dict[str, Any]:
    """Build a filter from validated, typed values only.

    No user-supplied string ever becomes a MongoDB operator key: every key here
    is a literal written in this function (SOUL.md §10).
    """
    conditions: dict[str, Any] = {}
    if vessel_type is not None:
        conditions["vesselType"] = vessel_type
    if transceiver in {"A", "B"}:
        conditions["transceiverClass"] = transceiver
    speed: dict[str, float] = {}
    if min_speed is not None:
        speed["$gte"] = min_speed
    if max_speed is not None:
        speed["$lte"] = max_speed
    if speed:
        conditions["speedOverGroundKnots"] = speed
    if family is not None:
        # Family is a derived label, not a stored field. Translate it back to the
        # concrete codes it covers so the query stays indexable.
        codes = [code for code in range(100) if describe_vessel_type(code).family == family]
        if codes:
            conditions["vesselType"] = {"$in": codes}
    return conditions


async def find_nearby(
    database: AsyncDatabase[dict[str, Any]],
    *,
    longitude: float,
    latitude: float,
    radius_km: float,
    limit: int = 50,
    vessel_type: int | None = None,
) -> list[schemas.NearbyVessel]:
    """Vessels within ``radius_km``, nearest first.

    Uses ``$geoNear``, which is the right operator when the *ordering* by
    distance is part of the answer — it returns the computed distance and can
    only appear as the first pipeline stage. ``$geoWithin`` would answer
    containment but would not rank or measure.

    The radius is capped server-side; there is no way to ask for a global scan.
    """
    if radius_km <= 0 or radius_km > MAX_RADIUS_KM:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            f"radiusKm must be between 0 and {MAX_RADIUS_KM:g}.",
            status_code=400,
            details={"maxRadiusKm": MAX_RADIUS_KM},
        )

    pipeline: list[dict[str, Any]] = [
        {
            "$geoNear": {
                "near": {"type": "Point", "coordinates": [longitude, latitude]},
                "distanceField": "distanceMeters",
                "maxDistance": radius_km * 1000.0,
                "spherical": True,
                "query": _vessel_filters(vessel_type, None, None, None, None),
            }
        },
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

    results: list[schemas.NearbyVessel] = []
    async for document in await database[collections.VESSEL_LATEST].aggregate(pipeline):
        distance_km = float(document["distanceMeters"]) / 1000.0
        vessel = document.get("vessel") or {
            "_id": document["_id"],
            "name": document.get("name"),
            "vesselType": document.get("vesselType"),
        }
        results.append(
            schemas.NearbyVessel(
                vessel=mappers.to_vessel_summary(vessel),
                coordinates=mappers.to_coordinates(document.get("location")),
                timestamp=document["timestamp"],
                distance_km=round(distance_km, 3),
                distance_nautical_miles=round(km_to_nautical_miles(distance_km), 3),
                speed_over_ground_knots=document.get("speedOverGroundKnots"),
            )
        )
    return results


async def map_viewport(
    database: AsyncDatabase[dict[str, Any]],
    *,
    bounds: BoundingBox,
    limit: int = 2_000,
    vessel_type: int | None = None,
    family: str | None = None,
    transceiver: str | None = None,
    min_speed: float | None = None,
    max_speed: float | None = None,
    at_time: datetime | None = None,
) -> schemas.MapResponse:
    """Load vessels for a map viewport, clustering when zoomed far out.

    ``at_time`` switches the source from materialized latest state to a
    historical replay frame: the newest observation per vessel *at or before*
    that instant. That is a genuinely more expensive query, so it is bounded by
    both the viewport and a time floor.
    """
    filters = _vessel_filters(vessel_type, family, transceiver, min_speed, max_speed)
    geo_filter = bounds.to_geo_query()
    match_stage: dict[str, Any] = {**filters, **geo_filter} if filters else geo_filter

    if at_time is not None:
        return await _replay_viewport(database, match_stage, at_time=at_time, limit=limit)

    total = await database[collections.VESSEL_LATEST].count_documents(match_stage)

    if bounds.approximate_area_deg2() > CLUSTER_AREA_THRESHOLD_DEG2 and total > limit:
        return await _clustered_viewport(database, match_stage, total=total)

    documents = [
        document
        async for document in database[collections.VESSEL_LATEST]
        .find(match_stage, _MAP_FIELDS)
        .limit(limit)
    ]
    return schemas.MapResponse(
        mode="vessels",
        vessels=[mappers.to_map_vessel(document) for document in documents],
        total_in_viewport=total,
        truncated=total > len(documents),
    )


async def _clustered_viewport(
    database: AsyncDatabase[dict[str, Any]],
    match_stage: dict[str, Any],
    *,
    total: int,
) -> schemas.MapResponse:
    """Aggregate vessels into a coarse grid instead of sending them all.

    Grid cells are computed server-side with ``$floor`` on rounded coordinates,
    so the browser receives counts rather than 16k points it cannot render
    legibly anyway.
    """
    cell = 1.0
    pipeline: list[dict[str, Any]] = [
        {"$match": match_stage},
        {
            "$group": {
                "_id": {
                    "lon": {
                        "$floor": {
                            "$divide": [{"$arrayElemAt": ["$location.coordinates", 0]}, cell]
                        }
                    },
                    "lat": {
                        "$floor": {
                            "$divide": [{"$arrayElemAt": ["$location.coordinates", 1]}, cell]
                        }
                    },
                },
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"count": -1}},
        {"$limit": 1_500},
    ]
    clusters = [
        schemas.MapCluster(
            coordinates=schemas.Coordinates(
                longitude=(document["_id"]["lon"] + 0.5) * cell,
                latitude=(document["_id"]["lat"] + 0.5) * cell,
            ),
            count=document["count"],
        )
        async for document in await database[collections.VESSEL_LATEST].aggregate(pipeline)
    ]
    return schemas.MapResponse(mode="clusters", clusters=clusters, total_in_viewport=total)


async def _replay_viewport(
    database: AsyncDatabase[dict[str, Any]],
    geo_and_filters: dict[str, Any],
    *,
    at_time: datetime,
    limit: int,
) -> schemas.MapResponse:
    """Newest observation per vessel at or before ``at_time``, inside the viewport.

    This powers historical replay. It reads ``vessel_positions`` because
    materialized state only knows the final frame, and it is deliberately
    bounded: the viewport constrains the geometry and ``$top`` keeps one document
    per vessel rather than sorting the whole match.
    """
    geo_only = {key: value for key, value in geo_and_filters.items() if key in {"location", "$or"}}
    pipeline: list[dict[str, Any]] = [
        {"$match": {**geo_only, "timestamp": {"$lte": at_time}}},
        {"$sort": {"timestamp": -1}},
        {
            "$group": {
                "_id": "$mmsi",
                "doc": {"$top": {"sortBy": {"timestamp": -1}, "output": "$$ROOT"}},
            }
        },
        {"$replaceWith": "$doc"},
        {"$limit": limit},
        {
            "$lookup": {
                "from": collections.VESSEL_LATEST,
                "localField": "mmsi",
                "foreignField": "_id",
                "as": "state",
            }
        },
        {"$unwind": {"path": "$state", "preserveNullAndEmptyArrays": True}},
    ]

    vessels: list[schemas.MapVessel] = []
    async for document in await database[collections.VESSEL_POSITIONS].aggregate(pipeline):
        navigation = document.get("navigation") or {}
        state = document.get("state") or {}
        vessels.append(
            mappers.to_map_vessel(
                {
                    "mmsi": document["mmsi"],
                    "name": state.get("name"),
                    "location": document["location"],
                    "timestamp": document["timestamp"],
                    "headingDegrees": navigation.get("headingDegrees"),
                    "courseOverGroundDegrees": navigation.get("courseOverGroundDegrees"),
                    "speedOverGroundKnots": navigation.get("speedOverGroundKnots"),
                    "vesselType": state.get("vesselType"),
                }
            )
        )
    return schemas.MapResponse(
        mode="vessels",
        vessels=vessels,
        total_in_viewport=len(vessels),
        truncated=len(vessels) >= limit,
    )
