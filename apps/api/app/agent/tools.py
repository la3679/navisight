"""The copilot's tools: a fixed, allow-listed set of typed functions.

This module is the security boundary of the AI feature, and it is deliberately
boring.

**The model never authors a query.** It selects a name from the registry below
and supplies arguments that Pydantic validates before anything reaches MongoDB.
There is no tool that takes a filter document, an aggregation pipeline, a
projection, a sort, a collection name, or a field path. There is no tool that
evaluates a string. That is not a policy applied at runtime — it is the shape of
the registry, so the forbidden thing is unrepresentable rather than merely
disallowed (SOUL.md §8).

Categorically absent, with no exception for convenience:

- model-generated MongoDB queries, pipelines, or ``$where``;
- model-generated code of any kind;
- shell, filesystem, or network access;
- unbounded results — every tool caps its own limit, radius, and time range.

Each tool returns **bounded, structured, typed data** plus an evidence record
describing exactly what was asked and how much came back, so every number in an
answer can be traced to a call the user can inspect (SOUL.md §9).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from pymongo.asynchronous.database import AsyncDatabase

from app.api import schemas
from app.errors import ApiError, VesselNotFoundError
from app.services import analytics, dataset, geo, ports, vessels

#: Hard caps. A tool argument may ask for less; it can never ask for more.
MAX_ROWS = 25
MAX_RADIUS_KM = 100.0


# ---------------------------------------------------------------------------
# Argument models — the only shapes a model may produce
# ---------------------------------------------------------------------------
class NoArgs(BaseModel):
    """A tool that takes nothing. Declared rather than implied."""


class VesselQueryArgs(BaseModel):
    query: str = Field(
        min_length=1,
        max_length=64,
        description="Vessel name, MMSI, IMO, or call sign, or part of one.",
    )
    limit: int = Field(default=5, ge=1, le=MAX_ROWS)


class MmsiArgs(BaseModel):
    mmsi: str = Field(pattern=r"^\d{6,9}$", description="Maritime Mobile Service Identity.")


class LocationArgs(BaseModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    radius_km: float = Field(default=10.0, gt=0, le=MAX_RADIUS_KM, alias="radiusKm")
    limit: int = Field(default=10, ge=1, le=MAX_ROWS)

    model_config = {"populate_by_name": True}


class IntervalArgs(BaseModel):
    interval: str = Field(default="hour", pattern=r"^(hour|15min)$")


class LimitArgs(BaseModel):
    limit: int = Field(default=10, ge=1, le=MAX_ROWS)


class PortActivityArgs(BaseModel):
    port_id: str = Field(max_length=64, alias="portId")
    radius_km: float = Field(default=15.0, gt=0, le=MAX_RADIUS_KM, alias="radiusKm")
    limit: int = Field(default=10, ge=1, le=MAX_ROWS)

    model_config = {"populate_by_name": True}


class PortQueryArgs(BaseModel):
    query: str = Field(default="", max_length=64)
    limit: int = Field(default=10, ge=1, le=MAX_ROWS)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Tool:
    """One callable capability, fully described."""

    name: str
    description: str
    args_model: type[BaseModel]
    run: Callable[[AsyncDatabase[dict[str, Any]], Any], Awaitable[dict[str, Any]]]

    def json_schema(self) -> dict[str, Any]:
        """The argument schema, in the form a tool-calling API expects."""
        schema = self.args_model.model_json_schema(by_alias=True)
        schema.pop("title", None)
        # Providers reject unknown keywords in strict mode; $defs are inlined by
        # Pydantic for these flat models, so there is nothing to resolve.
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        schema["additionalProperties"] = False
        return schema


async def _dataset_overview(database: AsyncDatabase[dict[str, Any]], _: NoArgs) -> dict[str, Any]:
    status = await dataset.get_status(database)
    return {
        "datasetName": status.dataset,
        "isHistorical": True,
        "coverageStart": status.coverage.start,
        "coverageEnd": status.coverage.end,
        "positionReports": status.counts.positions,
        "distinctVessels": status.counts.vessels,
        "note": (
            "A single archived day. No position reflects where a vessel is now, and "
            "there is no data outside this window."
        ),
    }


async def _find_vessel(
    database: AsyncDatabase[dict[str, Any]], args: VesselQueryArgs
) -> dict[str, Any]:
    found = await vessels.search_vessels(database, query=args.query, limit=args.limit)
    return {
        "matches": [_summary(vessel) for vessel in found],
        "matchCount": len(found),
    }


async def _vessel_details(
    database: AsyncDatabase[dict[str, Any]], args: MmsiArgs
) -> dict[str, Any]:
    detail = await vessels.get_vessel(database, args.mmsi)
    if detail is None:
        raise VesselNotFoundError(args.mmsi)
    latest = await vessels.get_latest_observation(database, args.mmsi)
    if latest is None:
        raise VesselNotFoundError(args.mmsi)
    return {
        "vessel": {
            **_summary(detail),
            "lengthMeters": detail.dimensions.length_meters if detail.dimensions else None,
            "widthMeters": detail.dimensions.width_meters if detail.dimensions else None,
            "draftMeters": detail.dimensions.draft_meters if detail.dimensions else None,
            "firstSeenAt": detail.first_seen_at,
            "lastSeenAt": detail.last_seen_at,
            "observationCount": detail.observation_count,
        },
        "latestObservation": {
            "timestamp": latest.timestamp,
            "longitude": latest.coordinates.longitude,
            "latitude": latest.coordinates.latitude,
            "speedOverGroundKnots": latest.navigation.speed_over_ground_knots,
            "courseOverGroundDegrees": latest.navigation.course_over_ground_degrees,
            "headingDegrees": latest.navigation.heading_degrees,
            "navigationalStatus": latest.navigation.status_label,
        },
        "note": "'latestObservation' is the newest record in the archive, not a current position.",
    }


async def _vessel_track_summary(
    database: AsyncDatabase[dict[str, Any]], args: MmsiArgs
) -> dict[str, Any]:
    """Bounded statistics about a track, never the raw points.

    A 1,305-point path is not something to put through a language model: it
    would cost a fortune in tokens and invite arithmetic the model should not be
    doing. The numbers here are computed here.
    """
    track = await vessels.get_track(database, args.mmsi, max_points=500)
    points = track.points
    if not points:
        return {"mmsi": args.mmsi, "observationCount": 0, "note": "No observations."}

    longitudes = [point.coordinates.longitude for point in points]
    latitudes = [point.coordinates.latitude for point in points]
    speeds = [
        point.speed_over_ground_knots
        for point in points
        if point.speed_over_ground_knots is not None
    ]
    return {
        "mmsi": args.mmsi,
        "observationCount": track.meta.raw_point_count,
        "firstObservationAt": track.meta.start,
        "lastObservationAt": track.meta.end,
        "boundingBox": {
            "west": min(longitudes),
            "south": min(latitudes),
            "east": max(longitudes),
            "north": max(latitudes),
        },
        "speedKnots": {
            "min": min(speeds) if speeds else None,
            "max": max(speeds) if speeds else None,
            "mean": round(sum(speeds) / len(speeds), 2) if speeds else None,
            "reportedOn": len(speeds),
        },
        "simplifiedForRendering": track.meta.simplified,
        "interpolated": False,
        "note": (
            "Statistics over recorded observations only. The source is filtered to "
            "one-minute resolution and nothing between samples is interpolated."
        ),
    }


async def _vessels_near_location(
    database: AsyncDatabase[dict[str, Any]], args: LocationArgs
) -> dict[str, Any]:
    found = await geo.find_nearby(
        database,
        longitude=args.longitude,
        latitude=args.latitude,
        radius_km=args.radius_km,
        limit=args.limit,
    )
    return {
        "centre": {"longitude": args.longitude, "latitude": args.latitude},
        "radiusKm": args.radius_km,
        "vessels": [
            {
                **_summary(entry.vessel),
                "distanceKm": entry.distance_km,
                "distanceNauticalMiles": entry.distance_nautical_miles,
                "speedOverGroundKnots": entry.speed_over_ground_knots,
                "observedAt": entry.timestamp,
            }
            for entry in found
        ],
        "vesselCount": len(found),
        "note": (
            "Proximity at each vessel's LATEST archived observation. Two vessels listed "
            "here were not necessarily there at the same moment."
        ),
    }


async def _traffic_summary(
    database: AsyncDatabase[dict[str, Any]], args: IntervalArgs
) -> dict[str, Any]:
    coverage = await _coverage(database)
    if coverage is None:
        return {"buckets": [], "note": "No data imported."}
    start, end = coverage
    interval: Any = args.interval
    result = await analytics.traffic_over_time(database, start=start, end=end, interval=interval)
    return {
        "interval": result.interval,
        "totalObservations": result.total_observations,
        "buckets": [
            {
                "bucket": bucket.bucket,
                "observations": bucket.observations,
                "distinctVessels": bucket.distinct_vessels,
            }
            for bucket in result.buckets
        ],
    }


async def _vessel_type_distribution(
    database: AsyncDatabase[dict[str, Any]], _: NoArgs
) -> dict[str, Any]:
    result = await analytics.vessel_type_distribution(database)
    return {
        "basis": result.basis,
        "total": result.total,
        "categories": [
            {"label": category.label, "count": category.count}
            for category in result.categories[:MAX_ROWS]
        ],
    }


async def _speed_distribution(database: AsyncDatabase[dict[str, Any]], _: NoArgs) -> dict[str, Any]:
    coverage = await _coverage(database)
    start, end = coverage if coverage else (None, None)
    result = await analytics.speed_distribution(database, start=start, end=end)
    return {
        "total": result.total,
        "note": result.note,
        "buckets": [
            {
                "label": bucket.label,
                "lowerKnots": bucket.lower_knots,
                "upperKnots": bucket.upper_knots,
                "count": bucket.count,
            }
            for bucket in result.buckets
        ],
    }


async def _most_active_vessels(
    database: AsyncDatabase[dict[str, Any]], args: LimitArgs
) -> dict[str, Any]:
    coverage = await _coverage(database)
    if coverage is None:
        return {"vessels": [], "note": "No data imported."}
    start, end = coverage
    found = await analytics.most_active_vessels(database, start=start, end=end, limit=args.limit)
    return {
        "vessels": [
            {**_summary(entry.vessel), "observations": entry.observations} for entry in found
        ],
        "note": (
            "Ranked by number of broadcasts, which reflects transceiver class and "
            "reporting rate — not distance travelled or importance."
        ),
    }


async def _find_ports(
    database: AsyncDatabase[dict[str, Any]], args: PortQueryArgs
) -> dict[str, Any]:
    found = await ports.search(database, query=args.query or None, limit=args.limit)
    return {
        "ports": [
            {
                "id": port.id,
                "name": port.name,
                "country": port.country,
                "unlocode": port.unlocode,
                "longitude": port.coordinates.longitude,
                "latitude": port.coordinates.latitude,
            }
            for port in found
        ],
        "note": "Ports come from an operator-supplied gazetteer, not from the AIS data.",
    }


async def _port_activity(
    database: AsyncDatabase[dict[str, Any]], args: PortActivityArgs
) -> dict[str, Any]:
    result = await ports.activity(
        database, args.port_id, radius_km=args.radius_km, limit=args.limit
    )
    return {
        "port": {"id": result.port.id, "name": result.port.name},
        "radiusKm": result.radius_km,
        "vessels": [
            {**_summary(entry.vessel), "distanceKm": entry.distance_km} for entry in result.vessels
        ],
        "truncated": result.truncated,
        "note": (
            "Proximity, NOT a port call. AIS does not record berthing, cargo operations, "
            "or a declared destination."
        ),
    }


def _summary(vessel: schemas.VesselSummary) -> dict[str, Any]:
    return {
        "mmsi": vessel.mmsi,
        "name": vessel.name,
        "imo": vessel.imo,
        "callSign": vessel.call_sign,
        "vesselType": vessel.vessel_type.label,
    }


async def _coverage(
    database: AsyncDatabase[dict[str, Any]],
) -> tuple[datetime, datetime] | None:
    status = await dataset.get_status(database)
    if status.coverage.start is None or status.coverage.end is None:
        return None
    return status.coverage.start, status.coverage.end


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="get_dataset_overview",
        description=(
            "What this deployment holds: dataset name, the archived time window it "
            "covers, how many position reports and distinct vessels. Call this first "
            "when a question depends on what data exists or on when 'now' is."
        ),
        args_model=NoArgs,
        run=_dataset_overview,
    ),
    Tool(
        name="find_vessel",
        description=(
            "Search vessels by name, MMSI, IMO, or call sign. Use this to turn a name "
            "in the user's question into an MMSI before asking for details."
        ),
        args_model=VesselQueryArgs,
        run=_find_vessel,
    ),
    Tool(
        name="get_vessel_details",
        description=("Identity, dimensions, and the newest archived observation for one MMSI."),
        args_model=MmsiArgs,
        run=_vessel_details,
    ),
    Tool(
        name="get_vessel_track_summary",
        description=(
            "Bounded statistics for one vessel's path: observation count, time span, "
            "bounding box, and speed min/max/mean. Returns no raw coordinates."
        ),
        args_model=MmsiArgs,
        run=_vessel_track_summary,
    ),
    Tool(
        name="find_vessels_near_location",
        description=(
            "Vessels whose latest archived position lies within a radius of a "
            f"longitude/latitude. Radius is capped at {MAX_RADIUS_KM:g} km."
        ),
        args_model=LocationArgs,
        run=_vessels_near_location,
    ),
    Tool(
        name="get_traffic_summary",
        description=(
            "Position reports and distinct vessels per time bucket across the whole "
            "archived window, hourly or every 15 minutes."
        ),
        args_model=IntervalArgs,
        run=_traffic_summary,
    ),
    Tool(
        name="get_vessel_type_distribution",
        description="How many vessels of each type family are in the archive.",
        args_model=NoArgs,
        run=_vessel_type_distribution,
    ),
    Tool(
        name="get_speed_distribution",
        description="How observations divide across speed bands over the archived window.",
        args_model=NoArgs,
        run=_speed_distribution,
    ),
    Tool(
        name="get_most_active_vessels",
        description="Vessels with the most broadcasts in the archived window.",
        args_model=LimitArgs,
        run=_most_active_vessels,
    ),
    Tool(
        name="find_ports",
        description=(
            "Search the operator-supplied port gazetteer by name, country, or "
            "UN/LOCODE. Fails cleanly when no gazetteer has been loaded."
        ),
        args_model=PortQueryArgs,
        run=_find_ports,
    ),
    Tool(
        name="get_port_activity",
        description=(
            "Vessels whose latest archived position lies within a radius of a port. "
            "This is proximity, not a record of a port call."
        ),
        args_model=PortActivityArgs,
        run=_port_activity,
    ),
)

BY_NAME: dict[str, Tool] = {tool.name: tool for tool in TOOLS}


class ToolError(Exception):
    """A tool could not run. Reported to the model so it can adapt or stop."""


async def execute(
    database: AsyncDatabase[dict[str, Any]], name: str, raw_arguments: dict[str, Any]
) -> dict[str, Any]:
    """Validate and run one tool call.

    An unknown name is refused here rather than anywhere further in. A model
    that invents a tool gets told so, and nothing is dispatched.
    """
    tool = BY_NAME.get(name)
    if tool is None:
        raise ToolError(f"No tool named {name!r}. Available tools: {', '.join(sorted(BY_NAME))}.")
    try:
        arguments = tool.args_model.model_validate(raw_arguments or {})
    except Exception as exc:
        raise ToolError(f"Invalid arguments for {name}: {exc}") from exc

    try:
        return await tool.run(database, arguments)
    except ApiError as exc:
        # A domain error is information, not a crash: "that vessel is not in the
        # archive" is an answer the model should relay rather than retry.
        raise ToolError(f"{exc.code}: {exc.message}") from exc
