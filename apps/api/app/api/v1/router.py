"""NaviSight API v1 routes.

Handlers stay thin: validate, delegate to a service, return a typed model.
Query logic lives in ``app/services/`` so it can be tested without HTTP and
reused by the agent's tools without going back out through the network.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Query

from app import __version__
from app.api import schemas
from app.api.deps import (
    BoundingBoxDep,
    Db,
    LatitudeParam,
    LimitParam,
    LongitudeParam,
    MapLimitParam,
    TimeWindowDep,
    TrackPointsParam,
)
from app.config import get_settings
from app.db.client import ping
from app.domain.vessel_types import nav_status_codes
from app.errors import ErrorResponse, VesselNotFoundError
from app.services import analytics as analytics_service
from app.services import dataset as dataset_service
from app.services import geo as geo_service
from app.services import vessels as vessels_service

router = APIRouter(
    prefix="/api/v1",
    responses={
        422: {"model": ErrorResponse, "description": "Invalid request parameters"},
        503: {"model": ErrorResponse, "description": "A dependency is unavailable"},
    },
)

MmsiPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=16,
        pattern=r"^[0-9]{1,16}$",
        description="Maritime Mobile Service Identity. An identifier, matched exactly.",
    ),
]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@router.get("/health", response_model=schemas.HealthResponse, tags=["system"])
async def health() -> schemas.HealthResponse:
    """Liveness. Answers only whether the process is running.

    Deliberately does not touch the database: a liveness probe that fails when a
    dependency is down causes restarts that fix nothing.
    """
    return schemas.HealthResponse(status="ok", version=__version__)


@router.get("/ready", response_model=schemas.ReadyResponse, tags=["system"])
async def ready(database: Db) -> schemas.ReadyResponse:
    """Readiness: whether the API can actually serve data.

    Returns 200 with ``degraded`` rather than an error, so the frontend can
    render an informative state instead of a failed request.
    """
    settings = get_settings()
    database_up = await ping()
    has_data = False
    if database_up:
        status = await dataset_service.get_status(database)
        has_data = status.has_data
    return schemas.ReadyResponse(
        status="ready" if database_up and has_data else "degraded",
        database=database_up,
        has_data=has_data,
        ai_configured=settings.ai_enabled,
    )


# ---------------------------------------------------------------------------
# Vessels
# ---------------------------------------------------------------------------
@router.get("/vessels", response_model=list[schemas.VesselSummary], tags=["vessels"])
async def list_vessels(
    database: Db,
    q: Annotated[
        str | None,
        Query(
            max_length=64,
            description=(
                "Search by vessel name (anchored prefix match), or exact MMSI, IMO, "
                "or call sign. This is prefix matching, not full-text search."
            ),
        ),
    ] = None,
    vessel_type: Annotated[int | None, Query(ge=0, le=1024, alias="vesselType")] = None,
    family: Annotated[str | None, Query(max_length=48)] = None,
    has_imo: Annotated[bool | None, Query(alias="hasImo")] = None,
    limit: LimitParam = 25,
    skip: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> list[schemas.VesselSummary]:
    """Search vessels."""
    return await vessels_service.search_vessels(
        database,
        query=q,
        vessel_type=vessel_type,
        family=family,
        has_imo=has_imo,
        limit=limit,
        skip=skip,
    )


@router.get(
    "/vessels/{mmsi}",
    response_model=schemas.VesselDetail,
    tags=["vessels"],
    responses={404: {"model": ErrorResponse}},
)
async def get_vessel(database: Db, mmsi: MmsiPath) -> schemas.VesselDetail:
    """One vessel's identity, metadata, and activity window."""
    vessel = await vessels_service.get_vessel(database, mmsi)
    if vessel is None:
        raise VesselNotFoundError(mmsi)
    return vessel


@router.get(
    "/vessels/{mmsi}/latest",
    response_model=schemas.LatestObservation,
    tags=["vessels"],
    responses={404: {"model": ErrorResponse}},
)
async def get_latest(database: Db, mmsi: MmsiPath) -> schemas.LatestObservation:
    """The most recent observation **in the imported dataset**.

    Not a current position: this data is historical (ADR-0008).
    """
    latest = await vessels_service.get_latest_observation(database, mmsi)
    if latest is None:
        raise VesselNotFoundError(mmsi)
    return latest


@router.get(
    "/vessels/{mmsi}/positions",
    response_model=schemas.Paginated[schemas.Observation],
    tags=["vessels"],
)
async def get_positions(
    database: Db,
    mmsi: MmsiPath,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    limit: LimitParam = 100,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
) -> schemas.Paginated[schemas.Observation]:
    """A vessel's observations, newest first, cursor-paginated."""
    return await vessels_service.get_positions(
        database, mmsi, start=start, end=end, limit=limit, cursor=cursor
    )


@router.get("/vessels/{mmsi}/track", response_model=schemas.VesselTrack, tags=["vessels"])
async def get_track(
    database: Db,
    mmsi: MmsiPath,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    max_points: TrackPointsParam = 1_000,
) -> schemas.VesselTrack:
    """A vessel's path, simplified for map rendering.

    The response always reports the raw observation count, the returned point
    count, and the simplification method, so a simplified line is never
    presented as the complete record.
    """
    return await vessels_service.get_track(
        database, mmsi, start=start, end=end, max_points=max_points
    )


# ---------------------------------------------------------------------------
# Geospatial & map
# ---------------------------------------------------------------------------
@router.get("/geo/nearby", response_model=list[schemas.NearbyVessel], tags=["geo"])
async def nearby(
    database: Db,
    longitude: LongitudeParam,
    latitude: LatitudeParam,
    radius_km: Annotated[float, Query(alias="radiusKm", gt=0, le=500)] = 25.0,
    limit: LimitParam = 50,
    vessel_type: Annotated[int | None, Query(ge=0, le=1024, alias="vesselType")] = None,
) -> list[schemas.NearbyVessel]:
    """Vessels near a point, nearest first, with distances.

    Based on each vessel's latest known position in the dataset.
    """
    return await geo_service.find_nearby(
        database,
        longitude=longitude,
        latitude=latitude,
        radius_km=radius_km,
        limit=limit,
        vessel_type=vessel_type,
    )


@router.get("/map/vessels", response_model=schemas.MapResponse, tags=["map"])
async def map_vessels(
    database: Db,
    bounds: BoundingBoxDep,
    limit: MapLimitParam = 2_000,
    vessel_type: Annotated[int | None, Query(ge=0, le=1024, alias="vesselType")] = None,
    family: Annotated[str | None, Query(max_length=48)] = None,
    transceiver: Annotated[Literal["A", "B"] | None, Query()] = None,
    min_speed: Annotated[float | None, Query(ge=0, le=100, alias="minSpeed")] = None,
    max_speed: Annotated[float | None, Query(ge=0, le=100, alias="maxSpeed")] = None,
    at: Annotated[
        datetime | None,
        Query(
            description="Replay instant. Returns each vessel's newest observation "
            "at or before this time instead of its final state."
        ),
    ] = None,
) -> schemas.MapResponse:
    """Vessels in a map viewport.

    Returns individual vessels when the viewport is small enough to render them,
    and aggregated cells when it is not — the browser never receives the whole
    dataset. A viewport with ``west > east`` crosses the antimeridian and is
    handled correctly.
    """
    return await geo_service.map_viewport(
        database,
        bounds=bounds,
        limit=limit,
        vessel_type=vessel_type,
        family=family,
        transceiver=transceiver,
        min_speed=min_speed,
        max_speed=max_speed,
        at_time=at,
    )


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
@router.get("/analytics/traffic", response_model=schemas.TrafficResponse, tags=["analytics"])
async def traffic(
    database: Db,
    window: TimeWindowDep,
    interval: Annotated[Literal["hour", "15min"], Query()] = "hour",
) -> schemas.TrafficResponse:
    """Observation volume and distinct vessels over time."""
    return await analytics_service.traffic_over_time(
        database, start=window.start, end=window.end, interval=interval
    )


@router.get(
    "/analytics/vessel-types",
    response_model=schemas.DistributionResponse,
    tags=["analytics"],
)
async def vessel_types(database: Db) -> schemas.DistributionResponse:
    """Fleet composition by vessel-type family, counted per vessel."""
    return await analytics_service.vessel_type_distribution(database)


@router.get(
    "/analytics/transceivers",
    response_model=schemas.DistributionResponse,
    tags=["analytics"],
)
async def transceivers(database: Db) -> schemas.DistributionResponse:
    """Class A vs Class B transceiver split, counted per vessel."""
    return await analytics_service.transceiver_distribution(database)


@router.get(
    "/analytics/nav-status", response_model=schemas.DistributionResponse, tags=["analytics"]
)
async def nav_status(database: Db) -> schemas.DistributionResponse:
    """Reported navigational status across current vessel state."""
    return await analytics_service.navigation_status_distribution(database)


@router.get(
    "/analytics/speed", response_model=schemas.SpeedDistributionResponse, tags=["analytics"]
)
async def speed(
    database: Db,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
) -> schemas.SpeedDistributionResponse:
    """Speed-over-ground histogram across observations."""
    return await analytics_service.speed_distribution(database, start=start, end=end)


@router.get(
    "/analytics/active-vessels", response_model=list[schemas.ActiveVessel], tags=["analytics"]
)
async def active_vessels(
    database: Db, window: TimeWindowDep, limit: LimitParam = 20
) -> list[schemas.ActiveVessel]:
    """Vessels with the most observations in the window.

    This ranks broadcast frequency, which correlates with time underway but is
    not a distance-travelled ranking.
    """
    return await analytics_service.most_active_vessels(
        database, start=window.start, end=window.end, limit=limit
    )


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------
@router.get("/dataset/status", response_model=schemas.DatasetStatus, tags=["dataset"])
async def dataset_status(database: Db) -> schemas.DatasetStatus:
    """What is loaded, what period it covers, and what is configured."""
    return await dataset_service.get_status(database)


@router.get(
    "/dataset/quality",
    response_model=schemas.DataQualityResponse,
    tags=["dataset"],
    responses={404: {"model": ErrorResponse}},
)
async def dataset_quality() -> schemas.DataQualityResponse:
    """Field completeness of the source file, from the profiler's report."""
    quality = dataset_service.get_data_quality()
    if quality is None:
        from app.errors import ApiError, ErrorCode

        raise ApiError(
            ErrorCode.NOT_FOUND,
            "No profile report is available. Run `navisight-data profile`.",
            status_code=404,
        )
    return quality


@router.get("/reference/nav-status", response_model=dict[int, str], tags=["reference"])
async def reference_nav_status() -> dict[int, str]:
    """ITU-R M.1371 navigational status codes, for UI filter menus."""
    return nav_status_codes()


def build_openapi_tags() -> list[dict[str, Any]]:
    """Tag descriptions surfaced in the generated OpenAPI document."""
    return [
        {"name": "system", "description": "Liveness and readiness probes."},
        {"name": "vessels", "description": "Vessel identity, history, and tracks."},
        {"name": "geo", "description": "Proximity search over latest known positions."},
        {"name": "map", "description": "Viewport loading for the operations map."},
        {"name": "analytics", "description": "Aggregations over the imported dataset."},
        {"name": "dataset", "description": "What is loaded and how complete it is."},
        {"name": "reference", "description": "Static AIS code lookups."},
    ]
