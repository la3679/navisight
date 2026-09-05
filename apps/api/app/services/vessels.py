"""Vessel search, detail, history, and trajectory queries.

Every query here is bounded and projected. No route can request an unbounded
scan, and no query fetches fields it does not use.
"""

from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from app.api import schemas
from app.db import collections
from app.domain.geo import MAX_TRACK_POINTS, simplify_track
from app.errors import ApiError, ErrorCode
from app.services import mappers

#: Projections keep the wire and the working set small. `vessel_positions` has
#: 5.9M documents; not fetching `source` on a track query is free savings.
_VESSEL_FIELDS = {
    "mmsi": 1,
    "name": 1,
    "imo": 1,
    "callSign": 1,
    "vesselType": 1,
    "dimensions": 1,
    "cargo": 1,
    "firstSeenAt": 1,
    "lastSeenAt": 1,
    "metadataUpdatedAt": 1,
}
_POSITION_FIELDS = {"mmsi": 1, "timestamp": 1, "location": 1, "navigation": 1, "source": 1}
_TRACK_FIELDS = {"_id": 0, "timestamp": 1, "location": 1, "navigation": 1}

_SAFE_QUERY = re.compile(r"^[A-Za-z0-9 ._@/&()'-]{1,64}$")


def _escape_regex(value: str) -> str:
    """Escape a user string for safe use inside a regex.

    Search input becomes a *value*, never a pattern the user controls. Without
    this, a query of ``.*`` would turn a prefix lookup into a full scan, and a
    nested quantifier could be used to burn CPU.
    """
    return re.escape(value)


def _encode_cursor(timestamp: datetime) -> str:
    return base64.urlsafe_b64encode(timestamp.isoformat().encode()).decode()


def _decode_cursor(cursor: str) -> datetime:
    try:
        return datetime.fromisoformat(base64.urlsafe_b64decode(cursor.encode()).decode())
    except (ValueError, binascii.Error) as exc:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, "The pagination cursor is not valid.", status_code=400
        ) from exc


async def search_vessels(
    database: AsyncDatabase[dict[str, Any]],
    *,
    query: str | None = None,
    vessel_type: int | None = None,
    family: str | None = None,
    has_imo: bool | None = None,
    limit: int = 25,
    skip: int = 0,
) -> list[schemas.VesselSummary]:
    """Search vessels by name, MMSI, IMO, or call sign.

    Name matching is an **anchored prefix** (``/^QUERY/``), which the
    ``nameNormalized`` index can serve. It is not full-text search, and the API
    docs say so rather than implying fuzzy matching that does not exist
    (SOUL.md §7).
    """
    conditions: list[dict[str, Any]] = []

    if query:
        trimmed = query.strip()
        if trimmed:
            if not _SAFE_QUERY.match(trimmed):
                raise ApiError(
                    ErrorCode.VALIDATION_ERROR,
                    "Search terms may only contain letters, digits, spaces, and basic punctuation.",
                    status_code=400,
                )
            pattern = f"^{_escape_regex(trimmed.upper())}"
            alternatives: list[dict[str, Any]] = [
                {"nameNormalized": {"$regex": pattern}},
                {"callSign": trimmed.upper()},
                {"imo": trimmed.lstrip("IMOimo ").strip()},
            ]
            if trimmed.isdigit():
                # MMSI is an exact identifier lookup, not a prefix search.
                alternatives.append({"_id": trimmed})
            conditions.append({"$or": alternatives})

    if vessel_type is not None:
        conditions.append({"vesselType": vessel_type})
    if has_imo is True:
        conditions.append({"imo": {"$type": "string"}})
    elif has_imo is False:
        conditions.append({"imo": {"$exists": False}})

    filter_document: dict[str, Any] = {"$and": conditions} if conditions else {}

    cursor = (
        database[collections.VESSELS]
        .find(filter_document, _VESSEL_FIELDS)
        .sort("nameNormalized", 1)
        .skip(skip)
        .limit(limit)
    )
    documents = [document async for document in cursor]

    summaries = [mappers.to_vessel_summary(document) for document in documents]
    if family:
        summaries = [item for item in summaries if item.vessel_type.family == family]
    return summaries


async def get_vessel(
    database: AsyncDatabase[dict[str, Any]], mmsi: str
) -> schemas.VesselDetail | None:
    """Fetch one vessel with its observation count."""
    document = await database[collections.VESSELS].find_one({"_id": mmsi}, _VESSEL_FIELDS)
    if document is None:
        return None
    # Counted rather than stored, so it cannot drift out of date. Bounded by the
    # mmsi index, so it is an index-only count for one vessel.
    observation_count = await database[collections.VESSEL_POSITIONS].count_documents({"mmsi": mmsi})
    return mappers.to_vessel_detail(document, observation_count=observation_count)


async def get_latest_observation(
    database: AsyncDatabase[dict[str, Any]], mmsi: str
) -> schemas.LatestObservation | None:
    """Newest known observation for a vessel, from materialized state."""
    document = await database[collections.VESSEL_LATEST].find_one({"_id": mmsi})
    return mappers.to_latest_observation(document) if document else None


async def get_positions(
    database: AsyncDatabase[dict[str, Any]],
    mmsi: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 200,
    cursor: str | None = None,
) -> schemas.Paginated[schemas.Observation]:
    """Page through a vessel's observations, newest first.

    Cursor pagination on ``timestamp``: the compound ``(mmsi, timestamp desc)``
    index makes each page a bounded index range regardless of how deep the
    client has paged. An offset would degrade linearly.
    """
    time_filter: dict[str, Any] = {}
    if start is not None:
        time_filter["$gte"] = start
    if end is not None:
        time_filter["$lte"] = end
    if cursor is not None:
        # Strictly-less-than the last seen timestamp continues the descending page.
        time_filter["$lt"] = _decode_cursor(cursor)

    filter_document: dict[str, Any] = {"mmsi": mmsi}
    if time_filter:
        filter_document["timestamp"] = time_filter

    # Fetch one extra to detect a further page without a second query.
    documents = [
        document
        async for document in database[collections.VESSEL_POSITIONS]
        .find(filter_document, _POSITION_FIELDS)
        .sort("timestamp", -1)
        .limit(limit + 1)
    ]

    has_more = len(documents) > limit
    documents = documents[:limit]
    items = [mappers.to_observation(document) for document in documents]

    return schemas.Paginated(
        items=items,
        page=schemas.Page(
            next_cursor=_encode_cursor(documents[-1]["timestamp"]) if has_more else None,
            has_more=has_more,
            returned=len(items),
        ),
    )


async def get_track(
    database: AsyncDatabase[dict[str, Any]],
    mmsi: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    max_points: int = 1_000,
) -> schemas.VesselTrack:
    """Build a chronological, simplified track for map rendering.

    Two bounds apply. ``MAX_TRACK_POINTS`` caps how many observations are read
    from the database at all, and ``max_points`` caps how many are returned
    after simplification. The response always reports the raw count and the
    method used, so a simplified line is never mistaken for the full record
    (SOUL.md §4).
    """
    max_points = min(max_points, MAX_TRACK_POINTS)

    time_filter: dict[str, Any] = {}
    if start is not None:
        time_filter["$gte"] = start
    if end is not None:
        time_filter["$lte"] = end
    filter_document: dict[str, Any] = {"mmsi": mmsi}
    if time_filter:
        filter_document["timestamp"] = time_filter

    raw_points: list[dict[str, Any]] = []
    async for document in (
        database[collections.VESSEL_POSITIONS]
        .find(filter_document, _TRACK_FIELDS)
        .sort("timestamp", 1)
        .limit(MAX_TRACK_POINTS)
    ):
        coordinates = document["location"]["coordinates"]
        navigation = document.get("navigation") or {}
        raw_points.append(
            {
                "timestamp": document["timestamp"],
                "longitude": float(coordinates[0]),
                "latitude": float(coordinates[1]),
                "sog": navigation.get("speedOverGroundKnots"),
                "cog": navigation.get("courseOverGroundDegrees"),
            }
        )

    simplified = simplify_track(raw_points, max_points=max_points)
    points = [
        schemas.TrackPoint(
            timestamp=point["timestamp"],
            coordinates=schemas.Coordinates(
                longitude=point["longitude"], latitude=point["latitude"]
            ),
            speed_over_ground_knots=point["sog"],
            course_over_ground_degrees=point["cog"],
        )
        for point in simplified.points
    ]

    return schemas.VesselTrack(
        mmsi=mmsi,
        points=points,
        meta=schemas.TrackMeta(
            raw_point_count=simplified.raw_point_count,
            returned_point_count=simplified.returned_point_count,
            simplified=simplified.was_simplified,
            method=simplified.method,
            start=raw_points[0]["timestamp"] if raw_points else None,
            end=raw_points[-1]["timestamp"] if raw_points else None,
        ),
    )
