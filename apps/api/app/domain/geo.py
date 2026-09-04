"""Geospatial helpers: distances, bounding boxes, and trajectory simplification.

Pure functions, no I/O.

The antimeridian handling here is not defensive programming for a hypothetical.
The profiled dataset spans longitude -175.14678 to 146.49848 (US coastal waters
from Guam through Alaska to Maine), so a viewport around the Aleutians genuinely
produces ``west > east`` and a naive ``$box`` query would return the entire
world *except* the intended area.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

EARTH_RADIUS_KM = 6371.0088
KM_PER_NAUTICAL_MILE = 1.852

#: Enforced ceilings. Every one of these exists so no single request can ask the
#: database for an unbounded scan (SOUL.md §10).
MAX_RADIUS_KM = 500.0
MAX_TRACK_POINTS = 5_000
MAX_TIME_RANGE_HOURS = 24 * 7


def km_to_nautical_miles(km: float) -> float:
    """Convert kilometres to nautical miles, the conventional marine unit."""
    return km / KM_PER_NAUTICAL_MILE


def haversine_km(
    longitude_a: float, latitude_a: float, longitude_b: float, latitude_b: float
) -> float:
    """Great-circle distance in kilometres.

    Arguments are longitude-first to match GeoJSON and the rest of the codebase,
    so a caller never has to remember a different order for this one function.
    """
    phi_a, phi_b = math.radians(latitude_a), math.radians(latitude_b)
    delta_phi = phi_b - phi_a
    delta_lambda = math.radians(longitude_b - longitude_a)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """A map viewport in degrees.

    ``west > east`` means the box crosses the antimeridian, which is a normal
    state here rather than an error.
    """

    west: float
    south: float
    east: float
    north: float

    @property
    def crosses_antimeridian(self) -> bool:
        return self.west > self.east

    def to_geo_query(self) -> dict[str, Any]:
        """A MongoDB filter selecting points inside this box.

        A box that crosses the antimeridian is split into two boxes and combined
        with ``$or``. Passing the raw coordinates to a single ``$geoWithin``
        would select the complement of what the user is looking at.

        ``$box`` is used rather than ``$geoWithin: {$geometry: Polygon}`` because
        the viewport is a screen rectangle in degrees, and ``$box`` treats it as
        exactly that. A GeoJSON polygon would be interpreted with geodesic edges,
        which is not what a rectangular viewport means.

        **That choice has a measured cost, and it is not free.** ``$box`` is a
        legacy-coordinate operator, so a 2dsphere index cannot answer it:
        ``explain()`` reports ``COLLSCAN``, ``totalKeysExamined 0``,
        ``totalDocsExamined 16,294``. The same rectangle as a GeoJSON polygon
        uses ``latest_location_2dsphere`` (347 keys, 341 documents) and is about
        14x faster — 3.95 ms against 55.06 ms.

        It is kept anyway, for now, because the semantics are the ones the
        screen actually has and 55 ms over a collection bounded by *vessel
        count* is acceptable. The two forms returned an identical 338 documents
        for the benchmark's box, so the geodesic difference is invisible at this
        scale — but it is real at wide boxes and high latitudes, which is
        exactly where a silent change would be worst. Revisit if the fleet grows
        by an order of magnitude; the numbers to revisit it with are in
        ``docs/performance/BENCHMARKS.md``.
        """
        if not self.crosses_antimeridian:
            return {
                "location": {
                    "$geoWithin": {"$box": [[self.west, self.south], [self.east, self.north]]}
                }
            }
        return {
            "$or": [
                {
                    "location": {
                        "$geoWithin": {"$box": [[self.west, self.south], [180.0, self.north]]}
                    }
                },
                {
                    "location": {
                        "$geoWithin": {"$box": [[-180.0, self.south], [self.east, self.north]]}
                    }
                },
            ]
        }

    def approximate_area_deg2(self) -> float:
        """Rough size in square degrees, used to choose a clustering strategy."""
        width = (
            (self.east - self.west)
            if not self.crosses_antimeridian
            else ((180.0 - self.west) + (self.east + 180.0))
        )
        return abs(width) * abs(self.north - self.south)


SimplificationMethod = Literal["none", "douglas_peucker", "uniform_sample"]


@dataclass(frozen=True, slots=True)
class SimplifiedTrack:
    """A trajectory plus an honest account of what was done to it.

    SOUL.md §4: a simplified track must never be presented as complete raw
    telemetry, so the method and both point counts travel with the data and are
    surfaced in the API response.
    """

    points: list[dict[str, Any]]
    raw_point_count: int
    method: SimplificationMethod

    @property
    def returned_point_count(self) -> int:
        return len(self.points)

    @property
    def was_simplified(self) -> bool:
        return self.returned_point_count < self.raw_point_count


def _perpendicular_distance_km(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Distance from ``point`` to the segment ``start``-``end``, in km.

    Longitude degrees are scaled by ``cos(latitude)`` so the comparison is in
    real distance rather than degrees; without that, a tolerance would mean
    something different at the equator than in Alaska — and this dataset reaches
    85°N.
    """
    scale = math.cos(math.radians(start[1])) or 1e-9
    px, py = point[0] * scale, point[1]
    ax, ay = start[0] * scale, start[1]
    bx, by = end[0] * scale, end[1]

    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return haversine_km(point[0], point[1], start[0], start[1])

    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    nearest_x, nearest_y = ax + t * dx, ay + t * dy
    return haversine_km(point[0], point[1], nearest_x / scale, nearest_y)


def douglas_peucker(points: list[dict[str, Any]], *, tolerance_km: float) -> list[dict[str, Any]]:
    """Simplify a path, keeping the points that define its shape.

    Iterative rather than recursive: a vessel track can carry thousands of
    points and Python's recursion limit is a poor reason to fail a request.

    Each point must have ``longitude`` and ``latitude`` keys.
    """
    if len(points) < 3:
        return list(points)

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack: list[tuple[int, int]] = [(0, len(points) - 1)]

    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        start = (points[first]["longitude"], points[first]["latitude"])
        end = (points[last]["longitude"], points[last]["latitude"])

        furthest_index = -1
        furthest_distance = 0.0
        for index in range(first + 1, last):
            candidate = (points[index]["longitude"], points[index]["latitude"])
            distance = _perpendicular_distance_km(candidate, start, end)
            if distance > furthest_distance:
                furthest_distance = distance
                furthest_index = index

        if furthest_index != -1 and furthest_distance > tolerance_km:
            keep[furthest_index] = True
            stack.append((first, furthest_index))
            stack.append((furthest_index, last))

    return [point for point, kept in zip(points, keep, strict=True) if kept]


def uniform_sample(points: list[dict[str, Any]], *, max_points: int) -> list[dict[str, Any]]:
    """Evenly sample a path down to ``max_points``, always keeping the endpoints."""
    if len(points) <= max_points or max_points < 2:
        return list(points)
    step = (len(points) - 1) / (max_points - 1)
    sampled = [points[round(index * step)] for index in range(max_points)]
    if sampled[-1] is not points[-1]:
        sampled[-1] = points[-1]
    return sampled


def simplify_track(
    points: list[dict[str, Any]],
    *,
    max_points: int = 1_000,
    tolerance_km: float = 0.05,
) -> SimplifiedTrack:
    """Reduce a track to at most ``max_points``, preserving its shape.

    Douglas-Peucker is tried first because it keeps turns and drops only
    redundant straight-line points — the shape a person reads off a map survives.
    If that is still too many points (a genuinely complex track), a uniform
    sample enforces the ceiling.

    The result records which method ran and both point counts, so the API can
    tell the client the track is simplified rather than implying it is complete.
    """
    raw_count = len(points)
    if raw_count <= max_points:
        return SimplifiedTrack(points=list(points), raw_point_count=raw_count, method="none")

    reduced = douglas_peucker(points, tolerance_km=tolerance_km)
    if len(reduced) <= max_points:
        return SimplifiedTrack(points=reduced, raw_point_count=raw_count, method="douglas_peucker")

    return SimplifiedTrack(
        points=uniform_sample(reduced, max_points=max_points),
        raw_point_count=raw_count,
        method="uniform_sample",
    )
