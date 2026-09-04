"""Parsing and normalization of raw AIS CSV rows.

This module is pure: no I/O, no database, no configuration. It is the part of
the system most likely to be subtly wrong, so it is also the part that is
cheapest to test exhaustively.

The rules it implements come from :doc:`docs/data/AIS_SOURCE_REFERENCE.md`,
which transcribes the official NOAA/MarineCadastre data dictionary. Two of them
are load-bearing enough to restate here:

* ``base_date_time`` is documented as **UTC**. Parsed values are always
  timezone-aware UTC. A naive datetime never leaves this module.
* Optional fields that are empty, unparseable, or outside their documented
  domain become ``None`` — never ``0``. A missing heading is missing; it is not
  north. (SOUL.md §6.)

Rejection is reserved for rows that cannot yield a usable position event:
an unparseable timestamp, or a coordinate that is missing, unparseable, or
outside the physically valid range. Everything else is degraded to ``None`` and
counted, never silently coerced.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

# Column order of the 2025+ MarineCadastre AIS point schema. Parsing is done by
# *name* rather than position, so a reordered export still works; this tuple is
# the contract we validate the header against.
EXPECTED_COLUMNS: Final[tuple[str, ...]] = (
    "mmsi",
    "base_date_time",
    "longitude",
    "latitude",
    "sog",
    "cog",
    "heading",
    "vessel_name",
    "imo",
    "call_sign",
    "vessel_type",
    "status",
    "length",
    "width",
    "draft",
    "cargo",
    "transceiver",
)

# Physical limits. These are the *rejection* bounds — a point outside them
# cannot be placed on the earth and MongoDB's 2dsphere index would reject it.
MIN_LONGITUDE: Final = -180.0
MAX_LONGITUDE: Final = 180.0
MIN_LATITUDE: Final = -90.0
MAX_LATITUDE: Final = 90.0

# Documented domains from the data dictionary. These are *reporting* bounds:
# a value outside them is recorded as out-of-domain and stored as None, but it
# does not reject the row. See docs/data/AIS_SOURCE_REFERENCE.md.
SOG_DOMAIN: Final = (0.0, 99.9)
COG_DOMAIN: Final = (0.0, 359.9)
HEADING_DOMAIN: Final = (0, 359)
LENGTH_DOMAIN: Final = (1, 509)
WIDTH_DOMAIN: Final = (1, 61)
DRAFT_DOMAIN: Final = (0.1, 24.0)
# The dictionary says 1-14, but ITU-R M.1371 defines 0 ("under way using
# engine") and 15 ("undefined"), and 0 occurs in the source data. We accept the
# standard's range. Documented in AIS_SOURCE_REFERENCE.md rather than silently
# patched.
STATUS_DOMAIN: Final = (0, 15)
VESSEL_TYPE_DOMAIN: Final = (0, 1024)
CARGO_DOMAIN: Final = (0, 1024)

_TIMESTAMP_FORMATS: Final = (
    "%Y-%m-%d %H:%M:%S",  # the form used by the 2025+ daily CSV exports
    "%Y-%m-%dT%H:%M:%S",  # ISO form used by older exports and the dictionary
)


class RejectReason(StrEnum):
    """Why a source row could not become a position event.

    These are counted per ingestion run and reported. A run that rejects a
    meaningful fraction of its input is not successful (SOUL.md §6).
    """

    WRONG_FIELD_COUNT = "wrong_field_count"
    MISSING_MMSI = "missing_mmsi"
    INVALID_TIMESTAMP = "invalid_timestamp"
    MISSING_COORDINATE = "missing_coordinate"
    INVALID_COORDINATE = "invalid_coordinate"
    COORDINATE_OUT_OF_RANGE = "coordinate_out_of_range"


class RowRejectedError(Exception):
    """Raised when a row cannot yield a usable position event."""

    def __init__(self, reason: RejectReason, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)


@dataclass(frozen=True, slots=True)
class VesselMetadata:
    """Slow-changing vessel identity attributes carried on an AIS broadcast.

    Stored once per vessel in the ``vessels`` collection, not copied onto every
    position document (SOUL.md §7).
    """

    name: str | None
    imo: str | None
    call_sign: str | None
    vessel_type: int | None
    length: int | None
    width: int | None
    draft: float | None
    cargo: int | None

    @property
    def is_empty(self) -> bool:
        """True when the broadcast carried no usable metadata at all."""
        return all(
            value is None
            for value in (
                self.name,
                self.imo,
                self.call_sign,
                self.vessel_type,
                self.length,
                self.width,
                self.draft,
                self.cargo,
            )
        )


@dataclass(frozen=True, slots=True)
class AisRecord:
    """One normalized AIS observation.

    Splits cleanly into the two collections it feeds: the position/navigation
    fields become a ``vessel_positions`` document, and ``metadata`` is folded
    into the ``vessels`` document for this MMSI.
    """

    mmsi: str
    timestamp: datetime
    longitude: float
    latitude: float
    sog: float | None
    cog: float | None
    heading: int | None
    status: int | None
    transceiver: str | None
    metadata: VesselMetadata

    def fingerprint(self) -> bytes:
        """Deterministic identity for this observation, used as ``_id``.

        Idempotency depends entirely on this being stable across processes and
        runs, so it uses BLAKE2b rather than :func:`hash`, whose string hashing
        is randomized per process.

        Components are the source attributes that distinguish a genuine
        observation: MMSI, event time, position, and transceiver class. MMSI +
        timestamp alone is deliberately *not* assumed to be unique — the
        profiler measures both hypotheses and reports them in
        ``docs/data/AIS_PROFILE.md``. Two rows agreeing on all five components
        describe the same broadcast, so collapsing them is the correct
        idempotent behaviour rather than data loss.

        Returns 12 bytes, stored as BSON Binary — half the size of the
        equivalent hex string across millions of documents.
        """
        payload = "|".join(
            (
                self.mmsi,
                self.timestamp.isoformat(),
                f"{self.longitude:.5f}",
                f"{self.latitude:.5f}",
                self.transceiver or "",
            )
        )
        return hashlib.blake2b(payload.encode("utf-8"), digest_size=12).digest()


def clean_text(value: str | None, *, max_length: int) -> str | None:
    """Normalize a free-text AIS field.

    AIS text arrives space- or ``@``-padded from the radio layer. Empty results
    become ``None`` so that "absent" is represented one way rather than three.

    The value is *content*, never instruction — see SOUL.md §10. Nothing here
    interprets it.
    """
    if value is None:
        return None
    cleaned = value.strip().strip("@").strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


def normalize_mmsi(value: str | None) -> str:
    """Normalize an MMSI to its canonical string form.

    MMSI is an *identifier*, not a quantity: it is never used for arithmetic,
    and storing it as a string preserves any leading zeros that a numeric type
    would destroy. Nine digits is the ITU standard length, so shorter values
    are left-padded rather than silently accepted as a different identity.
    """
    if value is None:
        raise RowRejectedError(RejectReason.MISSING_MMSI)
    cleaned = value.strip()
    if not cleaned:
        raise RowRejectedError(RejectReason.MISSING_MMSI)
    if cleaned.isdigit() and len(cleaned) < 9:
        return cleaned.zfill(9)
    return cleaned


def normalize_imo(value: str | None) -> str | None:
    """Normalize an IMO number to bare digits.

    The source writes ``IMO9377509``. The prefix is a display convention, not
    part of the number, so it is stripped for storage and re-applied in the UI.
    A value that is not seven digits after stripping is kept verbatim rather
    than discarded — it may be a legitimate oddity, and profiling reports it.
    """
    cleaned = clean_text(value, max_length=12)
    if cleaned is None:
        return None
    upper = cleaned.upper()
    if upper.startswith("IMO"):
        upper = upper[3:].strip()
    return upper or None


def parse_timestamp(value: str | None) -> datetime:
    """Parse an AIS timestamp as timezone-aware UTC.

    The data dictionary documents ``base_date_time`` as "Full UTC date and
    time" (see docs/data/AIS_SOURCE_REFERENCE.md), so the source carries no
    offset and we attach UTC explicitly. Internal handling is UTC-only;
    conversion to a local zone happens at the presentation layer and is always
    labelled (SOUL.md §4).
    """
    if value is None or not value.strip():
        raise RowRejectedError(RejectReason.INVALID_TIMESTAMP, "empty")
    raw = value.strip()
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    # Fall back to ISO parsing for exports carrying fractional seconds or an
    # explicit offset; normalize whatever we get to UTC.
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise RowRejectedError(RejectReason.INVALID_TIMESTAMP, raw[:32]) from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def parse_coordinate(
    raw_longitude: str | None,
    raw_latitude: str | None,
) -> tuple[float, float]:
    """Parse and range-check a longitude/latitude pair.

    Returns ``(longitude, latitude)`` — GeoJSON order, which is also the source
    file's column order. Getting this backwards is the most common geospatial
    bug there is, so the tuple is ordered to match the storage format exactly
    and never re-ordered downstream (SOUL.md §7).

    Coordinates are mandatory: a position event without a position is not an
    observation, so failure rejects the row rather than degrading it.
    """
    if not (raw_longitude or "").strip() or not (raw_latitude or "").strip():
        raise RowRejectedError(RejectReason.MISSING_COORDINATE)
    try:
        longitude = float(raw_longitude)  # type: ignore[arg-type]
        latitude = float(raw_latitude)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise RowRejectedError(
            RejectReason.INVALID_COORDINATE, f"{raw_longitude!r},{raw_latitude!r}"
        ) from exc
    if not (MIN_LONGITUDE <= longitude <= MAX_LONGITUDE) or not (
        MIN_LATITUDE <= latitude <= MAX_LATITUDE
    ):
        raise RowRejectedError(RejectReason.COORDINATE_OUT_OF_RANGE, f"{longitude},{latitude}")
    return longitude, latitude


def parse_optional_float(
    value: str | None, *, domain: tuple[float, float] | None = None
) -> float | None:
    """Parse an optional float, returning ``None`` when absent or out of domain.

    Out-of-domain values are dropped rather than clamped: clamping would invent
    a measurement the sensor never reported.
    """
    if value is None or not value.strip():
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if domain is not None and not (domain[0] <= parsed <= domain[1]):
        return None
    return parsed


def parse_optional_int(value: str | None, *, domain: tuple[int, int] | None = None) -> int | None:
    """Parse an optional integer, returning ``None`` when absent or out of domain.

    Accepts values written as floats (``"70.0"``), which some exports produce
    for integer-typed columns.
    """
    if value is None or not value.strip():
        return None
    raw = value.strip()
    try:
        parsed = int(raw)
    except ValueError:
        try:
            as_float = float(raw)
        except ValueError:
            return None
        if not as_float.is_integer():
            return None
        parsed = int(as_float)
    if domain is not None and not (domain[0] <= parsed <= domain[1]):
        return None
    return parsed


def parse_transceiver(value: str | None) -> str | None:
    """Normalize the AIS transceiver class to ``A`` or ``B``.

    The documented domain is exactly ``A | B``; anything else is unknown rather
    than guessed at.
    """
    cleaned = clean_text(value, max_length=2)
    if cleaned is None:
        return None
    upper = cleaned.upper()
    return upper if upper in {"A", "B"} else None


def parse_row(row: dict[str, str]) -> AisRecord:
    """Normalize one raw CSV row into an :class:`AisRecord`.

    Raises :class:`RowRejectedError` when the row cannot yield a usable position
    event. Callers are expected to count rejections by
    :class:`RejectReason` rather than discard them.
    """
    mmsi = normalize_mmsi(row.get("mmsi"))
    timestamp = parse_timestamp(row.get("base_date_time"))
    longitude, latitude = parse_coordinate(row.get("longitude"), row.get("latitude"))

    metadata = VesselMetadata(
        name=clean_text(row.get("vessel_name"), max_length=24),
        imo=normalize_imo(row.get("imo")),
        call_sign=clean_text(row.get("call_sign"), max_length=8),
        vessel_type=parse_optional_int(row.get("vessel_type"), domain=VESSEL_TYPE_DOMAIN),
        length=parse_optional_int(row.get("length"), domain=LENGTH_DOMAIN),
        width=parse_optional_int(row.get("width"), domain=WIDTH_DOMAIN),
        draft=parse_optional_float(row.get("draft"), domain=DRAFT_DOMAIN),
        cargo=parse_optional_int(row.get("cargo"), domain=CARGO_DOMAIN),
    )

    return AisRecord(
        mmsi=mmsi,
        timestamp=timestamp,
        longitude=longitude,
        latitude=latitude,
        sog=parse_optional_float(row.get("sog"), domain=SOG_DOMAIN),
        cog=parse_optional_float(row.get("cog"), domain=COG_DOMAIN),
        heading=parse_optional_int(row.get("heading"), domain=HEADING_DOMAIN),
        status=parse_optional_int(row.get("status"), domain=STATUS_DOMAIN),
        transceiver=parse_transceiver(row.get("transceiver")),
        metadata=metadata,
    )
