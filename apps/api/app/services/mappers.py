"""Translation from stored documents to API models.

Kept in one place so the wire shape is defined once. Routes never touch a raw
document, and no route can accidentally leak an internal field.
"""

from __future__ import annotations

from typing import Any

from app.api import schemas
from app.domain.vessel_types import describe_nav_status, describe_vessel_type


def to_vessel_type_info(code: int | None) -> schemas.VesselTypeInfo:
    info = describe_vessel_type(code)
    return schemas.VesselTypeInfo(code=info.code, label=info.label, family=info.family)


def to_coordinates(location: dict[str, Any] | None) -> schemas.Coordinates:
    """Read a GeoJSON Point into a coordinate pair.

    The stored order is [longitude, latitude] and is unpacked in that order,
    once, here.
    """
    coordinates = (location or {}).get("coordinates") or [0.0, 0.0]
    return schemas.Coordinates(longitude=float(coordinates[0]), latitude=float(coordinates[1]))


def to_vessel_summary(document: dict[str, Any]) -> schemas.VesselSummary:
    return schemas.VesselSummary(
        mmsi=str(document.get("mmsi") or document.get("_id")),
        name=document.get("name"),
        imo=document.get("imo"),
        call_sign=document.get("callSign"),
        vessel_type=to_vessel_type_info(document.get("vesselType")),
    )


def to_vessel_detail(
    document: dict[str, Any], *, observation_count: int | None = None
) -> schemas.VesselDetail:
    dimensions = document.get("dimensions") or {}
    return schemas.VesselDetail(
        mmsi=str(document.get("mmsi") or document.get("_id")),
        name=document.get("name"),
        imo=document.get("imo"),
        call_sign=document.get("callSign"),
        vessel_type=to_vessel_type_info(document.get("vesselType")),
        dimensions=schemas.VesselDimensions(
            length_meters=dimensions.get("lengthMeters"),
            width_meters=dimensions.get("widthMeters"),
            draft_meters=dimensions.get("draftMeters"),
        )
        if dimensions
        else None,
        cargo=document.get("cargo"),
        first_seen_at=document.get("firstSeenAt"),
        last_seen_at=document.get("lastSeenAt"),
        metadata_updated_at=document.get("metadataUpdatedAt"),
        observation_count=observation_count,
    )


def to_navigation(navigation: dict[str, Any] | None) -> schemas.NavigationState:
    navigation = navigation or {}
    status = navigation.get("status")
    return schemas.NavigationState(
        speed_over_ground_knots=navigation.get("speedOverGroundKnots"),
        course_over_ground_degrees=navigation.get("courseOverGroundDegrees"),
        heading_degrees=navigation.get("headingDegrees"),
        status=status,
        status_label=describe_nav_status(status),
    )


def to_observation(document: dict[str, Any]) -> schemas.Observation:
    return schemas.Observation(
        mmsi=str(document["mmsi"]),
        timestamp=document["timestamp"],
        coordinates=to_coordinates(document.get("location")),
        navigation=to_navigation(document.get("navigation")),
        transceiver_class=(document.get("source") or {}).get("transceiver"),
    )


def to_latest_observation(document: dict[str, Any]) -> schemas.LatestObservation:
    """Map a ``vessel_latest`` document.

    Note the flat field layout: unlike ``vessel_positions``, latest state stores
    navigation fields at the top level and denormalizes a little metadata, which
    is what lets the map render without a join (ADR-0003).
    """
    status = document.get("status")
    return schemas.LatestObservation(
        mmsi=str(document.get("mmsi") or document.get("_id")),
        timestamp=document["timestamp"],
        coordinates=to_coordinates(document.get("location")),
        navigation=schemas.NavigationState(
            speed_over_ground_knots=document.get("speedOverGroundKnots"),
            course_over_ground_degrees=document.get("courseOverGroundDegrees"),
            heading_degrees=document.get("headingDegrees"),
            status=status,
            status_label=describe_nav_status(status),
        ),
        transceiver_class=document.get("transceiverClass"),
        name=document.get("name"),
        vessel_type=to_vessel_type_info(document.get("vesselType")),
    )


def to_map_vessel(document: dict[str, Any]) -> schemas.MapVessel:
    vessel_type = document.get("vesselType")
    return schemas.MapVessel(
        mmsi=str(document.get("mmsi") or document.get("_id")),
        name=document.get("name"),
        coordinates=to_coordinates(document.get("location")),
        timestamp=document["timestamp"],
        heading_degrees=document.get("headingDegrees"),
        course_over_ground_degrees=document.get("courseOverGroundDegrees"),
        speed_over_ground_knots=document.get("speedOverGroundKnots"),
        vessel_type=vessel_type,
        family=describe_vessel_type(vessel_type).family,
    )
