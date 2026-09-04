"""Port reference data: loading it, and reading it back.

Ports are **optional reference data that NaviSight does not ship**. The AIS
source says nothing about ports — it is a stream of vessel broadcasts — so any
port here comes from a separate gazetteer the operator chooses and loads. That
is a deliberate boundary:

- NaviSight does not own or redistribute a port list, and inventing one would
  put fabricated place names next to real vessel positions, which SOUL.md §9
  forbids outright;
- different operators care about different registries, and the schema below is
  small enough that any of them maps onto it.

Absent that file, every port surface reports **not configured** and explains
what to load. It is not an error and it is not an empty list pretending to be an
answer.

What a loaded port buys you is proximity: "which vessels were within N km of
this port at their last observation in the archive". That is a real question the
AIS data can answer once you have somewhere to stand.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pymongo import ReplaceOne
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.database import Database

from app.api import schemas
from app.db import collections
from app.errors import ApiError, ErrorCode
from app.services import mappers

#: Columns a CSV must provide. Everything else in the file is ignored, so an
#: export with fifty columns needs no preprocessing.
REQUIRED_COLUMNS = ("id", "name", "latitude", "longitude")
OPTIONAL_COLUMNS = ("country", "unlocode", "harbourSize", "harbourType")


@dataclass(frozen=True)
class PortRecord:
    """One port, after validation."""

    id: str
    name: str
    longitude: float
    latitude: float
    country: str | None
    unlocode: str | None
    harbour_size: str | None
    harbour_type: str | None

    def to_document(self, *, source: str) -> dict[str, Any]:
        return {
            "_id": self.id,
            "name": self.name,
            # GeoJSON order is [longitude, latitude]. Always. (SOUL.md §7)
            "location": {"type": "Point", "coordinates": [self.longitude, self.latitude]},
            "country": self.country,
            "unlocode": self.unlocode,
            "harbourSize": self.harbour_size,
            "harbourType": self.harbour_type,
            "source": source,
        }


class PortLoadError(ValueError):
    """The supplied file cannot be read as port reference data."""


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _coordinate(raw: str | float | None, *, name: str, limit: float, row: int) -> float:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise PortLoadError(f"row {row}: {name} is empty")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise PortLoadError(f"row {row}: {name} {raw!r} is not a number") from exc
    if not -limit <= value <= limit:
        raise PortLoadError(f"row {row}: {name} {value} is outside +-{limit:g}")
    return value


def _record(fields: dict[str, Any], *, row: int) -> PortRecord:
    identifier = _clean(str(fields.get("id") or ""))
    name = _clean(str(fields.get("name") or ""))
    if not identifier:
        raise PortLoadError(f"row {row}: id is empty")
    if not name:
        raise PortLoadError(f"row {row}: name is empty")
    return PortRecord(
        id=identifier,
        name=name,
        longitude=_coordinate(fields.get("longitude"), name="longitude", limit=180.0, row=row),
        latitude=_coordinate(fields.get("latitude"), name="latitude", limit=90.0, row=row),
        country=_clean(fields.get("country")),
        unlocode=_clean(fields.get("unlocode")),
        harbour_size=_clean(fields.get("harbourSize")),
        harbour_type=_clean(fields.get("harbourType")),
    )


def read_ports(path: Path) -> Iterator[PortRecord]:
    """Parse a CSV or GeoJSON port file, one validated record at a time.

    Streaming, like everything else that reads a file here: a gazetteer is small
    today, but "load the whole thing into a list first" is the habit that makes
    the next file a problem.

    A malformed row raises rather than being skipped. A port list is small and
    hand-fixable, and silently dropping entries would leave the operator
    believing they had loaded a complete registry (SOUL.md §6).
    """
    if not path.exists():
        raise PortLoadError(f"{path} does not exist")

    if path.suffix.lower() in {".json", ".geojson"}:
        payload = json.loads(path.read_text(encoding="utf-8"))
        features = payload.get("features")
        if not isinstance(features, list):
            raise PortLoadError(f"{path} is not a GeoJSON FeatureCollection")
        for index, feature in enumerate(features, start=1):
            geometry = (feature or {}).get("geometry") or {}
            coordinates = geometry.get("coordinates") or [None, None]
            properties = dict((feature or {}).get("properties") or {})
            properties.setdefault("id", feature.get("id"))
            properties["longitude"] = coordinates[0]
            properties["latitude"] = coordinates[1]
            yield _record(properties, row=index)
        return

    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise PortLoadError(
                f"{path} is missing required column(s): {', '.join(missing)}. "
                f"Required: {', '.join(REQUIRED_COLUMNS)}."
            )
        for index, row in enumerate(reader, start=1):
            yield _record(dict(row), row=index)


def load(
    database: Database[dict[str, Any]], path: Path, *, batch_size: int = 500
) -> dict[str, Any]:
    """Replace the port collection's contents from ``path``.

    Upserts by id rather than dropping first, so re-running with a corrected
    file updates in place and a failed run does not leave the collection empty.
    """
    from app.db import indexes

    indexes.ensure_indexes(database, only=collections.PORTS)

    source = path.name
    operations: list[ReplaceOne[dict[str, Any]]] = []
    written = 0

    def flush() -> None:
        nonlocal written
        if not operations:
            return
        result = database[collections.PORTS].bulk_write(operations, ordered=False)
        written += result.upserted_count + result.modified_count + result.matched_count
        operations.clear()

    for record in read_ports(path):
        document = record.to_document(source=source)
        operations.append(ReplaceOne({"_id": document["_id"]}, document, upsert=True))
        if len(operations) >= batch_size:
            flush()
    flush()

    return {
        "source": source,
        "written": written,
        "total": database[collections.PORTS].estimated_document_count(),
    }


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def to_port(document: dict[str, Any]) -> schemas.Port:
    """Map a stored port document onto the wire shape."""
    return schemas.Port(
        id=document["_id"],
        name=document["name"],
        coordinates=mappers.to_coordinates(document.get("location")),
        country=document.get("country"),
        unlocode=document.get("unlocode"),
        harbour_size=document.get("harbourSize"),
        harbour_type=document.get("harbourType"),
        source=document.get("source", "unknown"),
    )


async def search(
    database: AsyncDatabase[dict[str, Any]],
    *,
    query: str | None = None,
    limit: int = 50,
    skip: int = 0,
) -> list[schemas.Port]:
    """Ports matching a name, country, or UN/LOCODE fragment.

    The user's text becomes a value inside ``$regex``, never a key and never an
    operator, and it is escaped before it gets there — a port name is data, not
    a query fragment (SOUL.md §10).
    """
    await require_configured(database)

    filters: dict[str, Any] = {}
    if query:
        pattern = re.escape(query.strip())
        filters = {
            "$or": [
                {"name": {"$regex": pattern, "$options": "i"}},
                {"country": {"$regex": pattern, "$options": "i"}},
                {"unlocode": {"$regex": pattern, "$options": "i"}},
            ]
        }

    cursor = database[collections.PORTS].find(filters).sort("name", 1).skip(skip).limit(limit)
    return [to_port(document) async for document in cursor]


async def get(database: AsyncDatabase[dict[str, Any]], port_id: str) -> schemas.Port:
    await require_configured(database)
    document = await database[collections.PORTS].find_one({"_id": port_id})
    if document is None:
        raise ApiError(
            ErrorCode.PORT_NOT_FOUND,
            f"No port with id {port_id!r} is in the loaded reference data.",
            status_code=404,
        )
    return to_port(document)


async def activity(
    database: AsyncDatabase[dict[str, Any]],
    port_id: str,
    *,
    radius_km: float,
    limit: int = 50,
) -> schemas.PortActivity:
    """Vessels whose last archived position sits within ``radius_km`` of a port.

    This is a *proximity* answer, not a port call: AIS says where a vessel was,
    not that it berthed, loaded, or was even bound for the port it happens to be
    beside. The endpoint description and the UI both say so, because "vessels at
    the port" would be an interpretation dressed as an observation
    (SOUL.md §8).
    """
    from app.services import geo

    port = await get(database, port_id)
    # One over the limit, so "there were more" is measured rather than assumed.
    found = await geo.find_nearby(
        database,
        longitude=port.coordinates.longitude,
        latitude=port.coordinates.latitude,
        radius_km=radius_km,
        limit=limit + 1,
    )
    return schemas.PortActivity(
        port=port,
        radius_km=radius_km,
        vessels=found[:limit],
        truncated=len(found) > limit,
    )


async def require_configured(database: AsyncDatabase[dict[str, Any]]) -> None:
    """Raise the not-configured error unless port data has been loaded.

    A distinct code from "not found": nothing is broken and nothing is missing
    from the archive — a setup step has not been performed, and the client can
    render that differently (SOUL.md §11).
    """
    if await database[collections.PORTS].estimated_document_count() == 0:
        raise ApiError(
            ErrorCode.PORT_DATA_NOT_CONFIGURED,
            "No port reference data has been loaded. NaviSight does not ship a "
            "port gazetteer; load one with `navisight-data ports load <file>`.",
            status_code=409,
            details={"command": "navisight-data ports load <file>"},
        )
