"""Shared route dependencies: the database handle and bounded query parameters.

Bounds are declared here once and reused, so an endpoint cannot be added
without them. That is the mechanical enforcement of SOUL.md §10 — "all user
input is validated and bounded" — rather than a rule someone has to remember.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, Query
from pymongo.asynchronous.database import AsyncDatabase

from app.db.client import get_async_database
from app.domain.geo import MAX_RADIUS_KM, MAX_TIME_RANGE_HOURS, BoundingBox
from app.errors import ApiError, ErrorCode


async def database_dep() -> AsyncDatabase[dict[str, Any]]:
    """The application database."""
    return get_async_database()


Db = Annotated[AsyncDatabase[dict[str, Any]], Depends(database_dep)]

# --- Bounded scalars -------------------------------------------------------
LimitParam = Annotated[
    int, Query(ge=1, le=200, description="Maximum results. Hard-capped server-side.")
]
MapLimitParam = Annotated[
    int,
    Query(
        ge=1,
        le=5_000,
        description="Maximum vessels returned for a viewport. Beyond this the "
        "response is clustered or marked truncated.",
    ),
]
TrackPointsParam = Annotated[
    int,
    Query(
        ge=2,
        le=5_000,
        description="Maximum track points after simplification. The response "
        "always reports the raw count and the method used.",
    ),
]
RadiusKmParam = Annotated[
    float,
    Query(gt=0, le=MAX_RADIUS_KM, description=f"Search radius in km (max {MAX_RADIUS_KM:g})."),
]
LongitudeParam = Annotated[float, Query(ge=-180, le=180, description="Decimal degrees.")]
LatitudeParam = Annotated[float, Query(ge=-90, le=90, description="Decimal degrees.")]


class TimeWindow:
    """A validated, bounded time range.

    Defaults to the full extent of the imported data when unspecified, which is
    the useful default for a single-day historical dataset.
    """

    def __init__(self, start: datetime, end: datetime) -> None:
        self.start = start
        self.end = end


async def time_window(
    start: Annotated[
        datetime | None, Query(description="Inclusive start, ISO-8601. Treated as UTC.")
    ] = None,
    end: Annotated[
        datetime | None, Query(description="Inclusive end, ISO-8601. Treated as UTC.")
    ] = None,
) -> TimeWindow:
    """Resolve and bound a requested time range.

    A naive datetime is interpreted as UTC rather than rejected, because clients
    routinely send one; the interpretation is documented and consistent with
    ADR-0009. The range is capped so no request can ask for an unbounded scan.
    """
    resolved_end = end or datetime.now(UTC)
    resolved_start = start or (resolved_end - timedelta(hours=24))

    if resolved_start.tzinfo is None:
        resolved_start = resolved_start.replace(tzinfo=UTC)
    if resolved_end.tzinfo is None:
        resolved_end = resolved_end.replace(tzinfo=UTC)

    if resolved_start > resolved_end:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "start must be before end.", status_code=400)

    span_hours = (resolved_end - resolved_start).total_seconds() / 3600
    if span_hours > MAX_TIME_RANGE_HOURS:
        raise ApiError(
            ErrorCode.RANGE_TOO_LARGE,
            f"The requested range spans {span_hours:.0f} hours; the maximum is "
            f"{MAX_TIME_RANGE_HOURS}.",
            status_code=400,
            details={"maxHours": MAX_TIME_RANGE_HOURS},
        )
    return TimeWindow(resolved_start, resolved_end)


TimeWindowDep = Annotated[TimeWindow, Depends(time_window)]


async def bounding_box(
    west: Annotated[float, Query(ge=-180, le=180)],
    south: Annotated[float, Query(ge=-90, le=90)],
    east: Annotated[float, Query(ge=-180, le=180)],
    north: Annotated[float, Query(ge=-90, le=90)],
) -> BoundingBox:
    """Build a viewport from query parameters.

    ``west > east`` is accepted, not rejected: it means the viewport crosses the
    antimeridian, which genuinely occurs in this dataset (longitudes run from
    -175.1 to +146.5). :meth:`BoundingBox.to_geo_query` splits it into two boxes.
    """
    if south > north:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, "south must be less than north.", status_code=400
        )
    return BoundingBox(west=west, south=south, east=east, north=north)


BoundingBoxDep = Annotated[BoundingBox, Depends(bounding_box)]
