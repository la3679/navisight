"""API response models.

Raw MongoDB documents are never returned to a client. Everything crosses the
boundary through a model here, which fixes the wire shape, keeps internal
fields (like the binary position ``_id``) private, and gives the frontend a
generated OpenAPI schema it can trust.

Naming is camelCase on the wire and snake_case in Python, via
``serialization_alias``.

Optional fields are genuinely optional. The profiled dataset is missing heading
in 50.6% of rows and IMO in 60.1%, so ``None`` is the normal case, not an edge
case — and the UI renders it as an em dash rather than a zero (SOUL.md §11).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    """Base: camelCase on the wire, populated from snake_case internally."""

    model_config = ConfigDict(populate_by_name=True, ser_json_timedelta="float")


# ---------------------------------------------------------------------------
# Shared
# ---------------------------------------------------------------------------
class Coordinates(ApiModel):
    """A position. Longitude first, matching GeoJSON and the stored order."""

    longitude: float
    latitude: float


class VesselTypeInfo(ApiModel):
    """A ship-type code with its label. The raw code is always preserved."""

    code: int | None = None
    label: str
    family: str


class Page(ApiModel):
    """Cursor pagination metadata.

    Cursors rather than offsets: an offset scan over millions of position
    documents gets slower the deeper you page, and a cursor keyed on the sort
    field stays constant-cost.
    """

    next_cursor: str | None = Field(default=None, serialization_alias="nextCursor")
    has_more: bool = Field(default=False, serialization_alias="hasMore")
    returned: int = 0


class Paginated[T](ApiModel):
    items: list[T]
    page: Page


# ---------------------------------------------------------------------------
# Vessels
# ---------------------------------------------------------------------------
class VesselDimensions(ApiModel):
    length_meters: int | None = Field(default=None, serialization_alias="lengthMeters")
    width_meters: int | None = Field(default=None, serialization_alias="widthMeters")
    draft_meters: float | None = Field(default=None, serialization_alias="draftMeters")


class VesselSummary(ApiModel):
    """Enough to render a search result or a map tooltip."""

    mmsi: str
    name: str | None = None
    imo: str | None = None
    call_sign: str | None = Field(default=None, serialization_alias="callSign")
    vessel_type: VesselTypeInfo = Field(serialization_alias="vesselType")


class VesselDetail(VesselSummary):
    """Full vessel record for the detail page."""

    dimensions: VesselDimensions | None = None
    cargo: int | None = None
    first_seen_at: datetime | None = Field(default=None, serialization_alias="firstSeenAt")
    last_seen_at: datetime | None = Field(default=None, serialization_alias="lastSeenAt")
    metadata_updated_at: datetime | None = Field(
        default=None, serialization_alias="metadataUpdatedAt"
    )
    observation_count: int | None = Field(default=None, serialization_alias="observationCount")


class NavigationState(ApiModel):
    """What the vessel reported about its motion at one instant."""

    speed_over_ground_knots: float | None = Field(
        default=None, serialization_alias="speedOverGroundKnots"
    )
    course_over_ground_degrees: float | None = Field(
        default=None, serialization_alias="courseOverGroundDegrees"
    )
    heading_degrees: int | None = Field(default=None, serialization_alias="headingDegrees")
    status: int | None = None
    status_label: str = Field(serialization_alias="statusLabel")


class Observation(ApiModel):
    """One AIS observation.

    Named "observation" rather than "position update" on purpose: the publisher
    filters this data to one-minute resolution, so it is a sample of where the
    vessel was, not continuous telemetry (ADR-0008).
    """

    mmsi: str
    timestamp: datetime
    coordinates: Coordinates
    navigation: NavigationState
    transceiver_class: str | None = Field(default=None, serialization_alias="transceiverClass")


class LatestObservation(Observation):
    """The newest observation for a vessel **within the imported dataset**.

    Explicitly not "current position": the data is historical (ADR-0008).
    """

    name: str | None = None
    vessel_type: VesselTypeInfo = Field(serialization_alias="vesselType")


class TrackMeta(ApiModel):
    """How a returned track relates to the stored observations.

    Always present, so a client can never mistake a simplified line for the
    complete record.
    """

    raw_point_count: int = Field(serialization_alias="rawPointCount")
    returned_point_count: int = Field(serialization_alias="returnedPointCount")
    simplified: bool
    method: Literal["none", "douglas_peucker", "uniform_sample"]
    interpolated: bool = Field(
        default=False,
        description=(
            "Always false. NaviSight stores only real observations; no position "
            "is ever invented between them."
        ),
    )
    start: datetime | None = None
    end: datetime | None = None


class TrackPoint(ApiModel):
    timestamp: datetime
    coordinates: Coordinates
    speed_over_ground_knots: float | None = Field(
        default=None, serialization_alias="speedOverGroundKnots"
    )
    course_over_ground_degrees: float | None = Field(
        default=None, serialization_alias="courseOverGroundDegrees"
    )


class VesselTrack(ApiModel):
    mmsi: str
    points: list[TrackPoint]
    meta: TrackMeta


# ---------------------------------------------------------------------------
# Map & geospatial
# ---------------------------------------------------------------------------
class MapVessel(ApiModel):
    """Minimal payload for rendering one vessel on the map.

    Deliberately lean: this is sent thousands at a time, so every field must
    earn its bytes.
    """

    mmsi: str
    name: str | None = None
    coordinates: Coordinates
    timestamp: datetime
    heading_degrees: int | None = Field(default=None, serialization_alias="headingDegrees")
    course_over_ground_degrees: float | None = Field(
        default=None, serialization_alias="courseOverGroundDegrees"
    )
    speed_over_ground_knots: float | None = Field(
        default=None, serialization_alias="speedOverGroundKnots"
    )
    vessel_type: int | None = Field(default=None, serialization_alias="vesselType")
    family: str


class MapCluster(ApiModel):
    """An aggregated cell, returned instead of individual vessels when zoomed out.

    The browser never receives the whole dataset (SOUL.md §13); at low zoom the
    server aggregates and sends counts.
    """

    coordinates: Coordinates
    count: int


class MapResponse(ApiModel):
    mode: Literal["vessels", "clusters"]
    vessels: list[MapVessel] = Field(default_factory=list)
    clusters: list[MapCluster] = Field(default_factory=list)
    total_in_viewport: int = Field(serialization_alias="totalInViewport")
    truncated: bool = Field(
        default=False,
        description="True when more vessels matched than the response limit allows.",
    )


class NearbyVessel(ApiModel):
    vessel: VesselSummary
    coordinates: Coordinates
    timestamp: datetime
    distance_km: float = Field(serialization_alias="distanceKm")
    distance_nautical_miles: float = Field(serialization_alias="distanceNauticalMiles")
    speed_over_ground_knots: float | None = Field(
        default=None, serialization_alias="speedOverGroundKnots"
    )


class Port(ApiModel):
    """One port from the loaded reference gazetteer.

    ``source`` names the file it came from, because a port is the one thing in
    NaviSight that did not come from the AIS archive and the user is entitled to
    know which registry they are looking at.
    """

    id: str
    name: str
    coordinates: Coordinates
    country: str | None = None
    unlocode: str | None = None
    harbour_size: str | None = Field(default=None, serialization_alias="harbourSize")
    harbour_type: str | None = Field(default=None, serialization_alias="harbourType")
    source: str


class PortActivity(ApiModel):
    """Vessels near a port at their latest observation in the archive."""

    port: Port
    radius_km: float = Field(serialization_alias="radiusKm")
    vessels: list[NearbyVessel]
    truncated: bool = Field(
        description="True when more vessels were within the radius than the limit allows."
    )


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
class TimeBucket(ApiModel):
    bucket: datetime
    observations: int
    distinct_vessels: int | None = Field(default=None, serialization_alias="distinctVessels")


class TrafficResponse(ApiModel):
    buckets: list[TimeBucket]
    interval: Literal["hour", "15min"]
    start: datetime
    end: datetime
    total_observations: int = Field(serialization_alias="totalObservations")
    computed_at: datetime | None = Field(
        default=None,
        serialization_alias="computedAt",
        description=(
            "When these figures were computed, if they came from the precomputed "
            "rollup. Absent means they were aggregated live for this request. The "
            "numbers are identical either way; this says which path produced them."
        ),
    )


class CategoryCount(ApiModel):
    key: str
    label: str
    count: int


class DistributionResponse(ApiModel):
    categories: list[CategoryCount]
    total: int
    basis: str = Field(
        description="Which collection the distribution was computed over, stated "
        "so a reader knows whether it counts vessels or observations."
    )


class SpeedBucket(ApiModel):
    label: str
    lower_knots: float = Field(serialization_alias="lowerKnots")
    upper_knots: float | None = Field(default=None, serialization_alias="upperKnots")
    count: int


class SpeedDistributionResponse(ApiModel):
    buckets: list[SpeedBucket]
    total: int
    note: str
    computed_at: datetime | None = Field(
        default=None,
        serialization_alias="computedAt",
        description=(
            "When these figures were computed, if they came from the precomputed "
            "rollup. Absent means they were aggregated live for this request."
        ),
    )


class ActiveVessel(ApiModel):
    vessel: VesselSummary
    observations: int


# ---------------------------------------------------------------------------
# Dataset status
# ---------------------------------------------------------------------------
class DatasetCoverage(ApiModel):
    start: datetime | None = None
    end: datetime | None = None


class DatasetCounts(ApiModel):
    positions: int
    vessels: int
    latest_states: int = Field(serialization_alias="latestStates")


class IngestionSummary(ApiModel):
    status: str | None = None
    source_file: str | None = Field(default=None, serialization_alias="sourceFile")
    started_at: datetime | None = Field(default=None, serialization_alias="startedAt")
    completed_at: datetime | None = Field(default=None, serialization_alias="completedAt")
    rows_read: int | None = Field(default=None, serialization_alias="rowsRead")
    positions_inserted: int | None = Field(default=None, serialization_alias="positionsInserted")
    positions_duplicate: int | None = Field(default=None, serialization_alias="positionsDuplicate")
    rows_rejected: int | None = Field(default=None, serialization_alias="rowsRejected")


class DatasetStatus(ApiModel):
    """What is loaded, so the UI can be honest about the data it is showing."""

    configured: bool
    has_data: bool = Field(serialization_alias="hasData")
    dataset: str
    is_historical: Literal[True] = Field(
        default=True,
        serialization_alias="isHistorical",
        description=(
            "Always true. NaviSight replays a historical AIS record; it is not a "
            "live feed and must never be presented as one (ADR-0008)."
        ),
    )
    counts: DatasetCounts
    coverage: DatasetCoverage
    last_ingestion: IngestionSummary | None = Field(
        default=None, serialization_alias="lastIngestion"
    )
    ports_configured: bool = Field(serialization_alias="portsConfigured")
    ai_configured: bool = Field(serialization_alias="aiConfigured")


class DataQualityField(ApiModel):
    field: str
    present: int
    missing: int
    missing_percent: float = Field(serialization_alias="missingPercent")


class DataQualityResponse(ApiModel):
    """Completeness of the imported data, from the committed profile report."""

    source: str
    rows_read: int = Field(serialization_alias="rowsRead")
    rows_rejected: int = Field(serialization_alias="rowsRejected")
    exact_duplicates: int = Field(serialization_alias="exactDuplicates")
    fields: list[DataQualityField]
    generated_at: datetime | None = Field(default=None, serialization_alias="generatedAt")


class HealthResponse(ApiModel):
    status: Literal["ok"]
    version: str


class ReadyResponse(ApiModel):
    status: Literal["ready", "degraded"]
    database: bool
    has_data: bool = Field(serialization_alias="hasData")
    ai_configured: bool = Field(serialization_alias="aiConfigured")


# Bounded query parameter aliases, reused across routes so a limit cannot be
# forgotten on one endpoint.
Limit = Annotated[int, Field(ge=1, le=500)]
MapLimit = Annotated[int, Field(ge=1, le=5_000)]
Any_ = Any  # re-exported for handlers that build raw filter dicts
