"""Streaming profiler for raw AIS CSV files.

Runs in a single bounded-memory pass. The source file is ~577 MiB / 5.9M rows;
it is never loaded whole, and pandas is deliberately not used (SOUL.md §17).

The point of this tool is to make schema and index decisions *evidence-based*.
In particular it answers the two questions the data model depends on:

1. **Is ``(mmsi, timestamp)`` unique?** The ingestion fingerprint's composition
   depends on the answer, and guessing it would be a correctness bug hiding as
   an assumption.
2. **How many distinct vessels are there?** This decides whether vessel
   metadata can be accumulated in memory during ingestion or needs a
   spill-to-database strategy.

Memory strategy: MMSI and timestamp strings are mapped to dense integer ids and
packed into a single machine int per row, so duplicate detection is *exact*
rather than probabilistic — no hash-collision caveat attached to the headline
numbers.
"""

from __future__ import annotations

import csv
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from app.domain.ais import (
    COG_DOMAIN,
    DRAFT_DOMAIN,
    EXPECTED_COLUMNS,
    HEADING_DOMAIN,
    LENGTH_DOMAIN,
    MAX_LATITUDE,
    MAX_LONGITUDE,
    MIN_LATITUDE,
    MIN_LONGITUDE,
    SOG_DOMAIN,
    STATUS_DOMAIN,
    WIDTH_DOMAIN,
    RejectReason,
    RowRejectedError,
    normalize_imo,
    parse_timestamp,
)
from app.domain.vessel_types import describe_vessel_type

# Raise the field-size limit: AIS text fields are short, but a malformed quote
# in a 577 MiB file should surface as a parse error we count, not a hard crash.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

_TS_ID_BITS: Final = 20  # up to 1,048,576 distinct timestamps (a day at 1 s = 86,400)
_LAT_SHIFT: Final = 2
_LON_SHIFT: Final = 27
_COORD_SCALE: Final = 100_000  # 5 decimal places, matching the documented resolution
_LON_OFFSET: Final = 18_000_000
_LAT_OFFSET: Final = 9_000_000

#: Speed buckets in knots, chosen to separate the operationally distinct
#: regimes: stopped, manoeuvring, transit, and fast craft.
SOG_BUCKETS: Final[tuple[float, ...]] = (0.0, 0.5, 1.0, 3.0, 5.0, 10.0, 15.0, 20.0, 30.0)


@dataclass
class ColumnStats:
    """Per-column presence and parse accounting."""

    present: int = 0
    """Non-empty in the source."""

    empty: int = 0
    """Present as a column but blank."""

    malformed: int = 0
    """Non-empty but not parseable as the documented type."""

    out_of_domain: int = 0
    """Parsed, but outside the domain the data dictionary documents."""


@dataclass
class ProfileResult:
    """Everything the profiler measured. Serialized to JSON and Markdown."""

    source_path: str
    source_bytes: int
    header: list[str]
    header_matches_expected: bool

    rows_read: int = 0
    rows_valid: int = 0
    rows_rejected: int = 0
    reject_reasons: Counter[str] = field(default_factory=Counter)

    # --- Identity ---------------------------------------------------------
    unique_mmsi: int = 0
    unique_vessel_names: int = 0
    unique_imo: int = 0
    unique_call_signs: int = 0
    mmsi_length_distribution: Counter[int] = field(default_factory=Counter)
    mmsi_leading_digit_distribution: Counter[str] = field(default_factory=Counter)

    # --- Uniqueness hypotheses (drives the ingestion fingerprint) ---------
    duplicate_mmsi_timestamp_pairs: int = 0
    """Rows whose (mmsi, timestamp) was already seen."""

    exact_duplicate_rows: int = 0
    """Of those, rows also identical in position and transceiver."""

    conflicting_mmsi_timestamp_rows: int = 0
    """Of those, rows with the SAME (mmsi, timestamp) but a DIFFERENT position."""

    # --- Time -------------------------------------------------------------
    timestamp_min: str | None = None
    timestamp_max: str | None = None
    rows_by_hour: Counter[int] = field(default_factory=Counter)
    distinct_timestamps: int = 0

    # --- Space ------------------------------------------------------------
    longitude_min: float | None = None
    longitude_max: float | None = None
    latitude_min: float | None = None
    latitude_max: float | None = None
    invalid_longitude: int = 0
    invalid_latitude: int = 0
    null_island_rows: int = 0
    """Rows at exactly (0, 0) — valid coordinates, but almost always a sensor default."""

    # --- Columns ----------------------------------------------------------
    columns: dict[str, ColumnStats] = field(default_factory=dict)

    # --- Distributions ----------------------------------------------------
    vessel_type_counts: Counter[int] = field(default_factory=Counter)
    status_counts: Counter[int] = field(default_factory=Counter)
    transceiver_counts: Counter[str] = field(default_factory=Counter)
    sog_histogram: Counter[str] = field(default_factory=Counter)
    sog_min: float | None = None
    sog_max: float | None = None

    # --- Per-vessel -------------------------------------------------------
    top_vessels_by_observations: list[dict[str, Any]] = field(default_factory=list)
    observations_per_vessel_percentiles: dict[str, int] = field(default_factory=dict)
    vessels_with_metadata_changes: int = 0
    total_metadata_changes: int = 0
    max_metadata_changes_for_one_vessel: int = 0
    vessels_with_imo: int = 0
    vessels_with_name: int = 0

    duration_seconds: float = 0.0
    rows_per_second: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable form, with Counters flattened to plain dicts."""

        def counter(c: Counter[Any], *, top: int | None = None) -> dict[str, int]:
            items = c.most_common(top) if top else sorted(c.items(), key=lambda kv: str(kv[0]))
            return {str(k): v for k, v in items}

        def pct(n: int) -> float:
            """Percentage of total rows read, guarding an empty file."""
            return round(100.0 * n / self.rows_read, 4) if self.rows_read else 0.0

        return {
            "source": {
                "path": self.source_path,
                "bytes": self.source_bytes,
                "header": self.header,
                "header_matches_expected_schema": self.header_matches_expected,
            },
            "rows": {
                "read": self.rows_read,
                "valid": self.rows_valid,
                "rejected": self.rows_rejected,
                "rejected_pct": pct(self.rows_rejected),
                "reject_reasons": counter(self.reject_reasons),
            },
            "identity": {
                "unique_mmsi": self.unique_mmsi,
                "unique_vessel_names": self.unique_vessel_names,
                "unique_imo": self.unique_imo,
                "unique_call_signs": self.unique_call_signs,
                "mmsi_length_distribution": counter(self.mmsi_length_distribution),
                "mmsi_leading_digit_distribution": counter(self.mmsi_leading_digit_distribution),
                "vessels_with_name": self.vessels_with_name,
                "vessels_with_imo": self.vessels_with_imo,
            },
            "uniqueness": {
                "duplicate_mmsi_timestamp_pairs": self.duplicate_mmsi_timestamp_pairs,
                "exact_duplicate_rows": self.exact_duplicate_rows,
                "conflicting_mmsi_timestamp_rows": self.conflicting_mmsi_timestamp_rows,
                "mmsi_timestamp_is_unique": self.duplicate_mmsi_timestamp_pairs == 0,
                "mmsi_timestamp_position_transceiver_is_unique": self.exact_duplicate_rows == 0,
            },
            "time": {
                "min": self.timestamp_min,
                "max": self.timestamp_max,
                "distinct_timestamps": self.distinct_timestamps,
                "rows_by_hour_utc": counter(self.rows_by_hour),
            },
            "space": {
                "longitude_min": self.longitude_min,
                "longitude_max": self.longitude_max,
                "latitude_min": self.latitude_min,
                "latitude_max": self.latitude_max,
                "invalid_longitude": self.invalid_longitude,
                "invalid_latitude": self.invalid_latitude,
                "null_island_rows": self.null_island_rows,
            },
            "columns": {
                name: {
                    "present": s.present,
                    "empty": s.empty,
                    "missing_pct": pct(s.empty),
                    "malformed": s.malformed,
                    "out_of_domain": s.out_of_domain,
                }
                for name, s in self.columns.items()
            },
            "distributions": {
                "vessel_type": counter(self.vessel_type_counts, top=40),
                "vessel_type_labels": {
                    str(code): describe_vessel_type(code).label
                    for code, _ in self.vessel_type_counts.most_common(40)
                },
                "status": counter(self.status_counts),
                "transceiver": counter(self.transceiver_counts),
                "sog_knots_histogram": counter(self.sog_histogram),
                "sog_min": self.sog_min,
                "sog_max": self.sog_max,
            },
            "per_vessel": {
                "top_by_observations": self.top_vessels_by_observations,
                "observations_percentiles": self.observations_per_vessel_percentiles,
                "vessels_with_metadata_changes": self.vessels_with_metadata_changes,
                "total_metadata_changes": self.total_metadata_changes,
                "max_metadata_changes_for_one_vessel": self.max_metadata_changes_for_one_vessel,
            },
            "run": {
                "duration_seconds": round(self.duration_seconds, 2),
                "rows_per_second": round(self.rows_per_second, 1),
            },
        }


def _sog_bucket(value: float) -> str:
    """Label the speed bucket a value falls into."""
    previous = SOG_BUCKETS[0]
    if value <= previous:
        return f"{previous:g}"
    for edge in SOG_BUCKETS[1:]:
        if value < edge:
            return f"{previous:g}-{edge:g}"
        previous = edge
    return f"{previous:g}+"


def _percentiles(sorted_values: list[int]) -> dict[str, int]:
    """p50/p90/p99/max over a sorted list, using nearest-rank."""
    if not sorted_values:
        return {}
    n = len(sorted_values)
    return {
        "min": sorted_values[0],
        "p50": sorted_values[min(n - 1, n // 2)],
        "p90": sorted_values[min(n - 1, (n * 90) // 100)],
        "p99": sorted_values[min(n - 1, (n * 99) // 100)],
        "max": sorted_values[-1],
    }


def _iter_rows(path: Path) -> Iterator[list[str]]:
    """Yield raw CSV rows, streaming, with a generous read buffer.

    ``newline=""`` is required by the csv module; the source uses CRLF endings.
    ``errors="replace"`` keeps a single bad byte from aborting a 5.9M-row run —
    the affected field then fails parsing and is counted as malformed rather
    than crashing the process.
    """
    with path.open("r", encoding="utf-8", newline="", errors="replace", buffering=1 << 20) as fh:
        yield from csv.reader(fh)


def profile_csv(
    path: Path,
    *,
    limit: int | None = None,
    progress: Callable[[int], None] | None = None,
    progress_every: int = 500_000,
    top_vessels: int = 25,
) -> ProfileResult:
    """Profile an AIS CSV in one streaming pass.

    Args:
        path: Source CSV. Opened read-only; never modified.
        limit: Stop after this many data rows. Used for smoke tests.
        progress: Called with the running row count every ``progress_every`` rows.
        progress_every: Row interval between progress callbacks.
        top_vessels: How many busiest vessels to report.

    Returns:
        A :class:`ProfileResult` containing only measured values.
    """
    started = time.perf_counter()
    rows = _iter_rows(path)

    try:
        header = next(rows)
    except StopIteration as exc:
        raise ValueError(f"{path} is empty") from exc

    # Strip a UTF-8 BOM if the export carries one.
    if header and header[0].startswith("﻿"):
        header[0] = header[0].lstrip("﻿")
    header = [column.strip().lower() for column in header]

    result = ProfileResult(
        source_path=str(path),
        source_bytes=path.stat().st_size,
        header=list(header),
        header_matches_expected=tuple(header) == EXPECTED_COLUMNS,
    )
    result.columns = {name: ColumnStats() for name in header}

    index = {name: position for position, name in enumerate(header)}
    expected_width = len(header)

    def column(row: list[str], name: str) -> str:
        position = index.get(name, -1)
        return row[position] if 0 <= position < len(row) else ""

    # Dense id assignment keeps duplicate detection exact and cheap.
    mmsi_ids: dict[str, int] = {}
    ts_ids: dict[str, int] = {}
    tx_ids: dict[str, int] = {"": 0, "A": 1, "B": 2}
    seen_positions: dict[int, int] = {}

    observations: Counter[int] = Counter()
    metadata_signature: dict[int, int] = {}
    metadata_changes: defaultdict[int, int] = defaultdict(int)
    vessel_display_name: dict[int, str] = {}
    vessel_type_by_mmsi: dict[int, int] = {}
    vessels_with_name: set[int] = set()
    vessels_with_imo: set[int] = set()

    names: set[str] = set()
    imos: set[str] = set()
    call_signs: set[str] = set()

    numeric_domains: dict[str, tuple[float, float]] = {
        "sog": SOG_DOMAIN,
        "cog": COG_DOMAIN,
        "heading": (float(HEADING_DOMAIN[0]), float(HEADING_DOMAIN[1])),
        "length": (float(LENGTH_DOMAIN[0]), float(LENGTH_DOMAIN[1])),
        "width": (float(WIDTH_DOMAIN[0]), float(WIDTH_DOMAIN[1])),
        "draft": DRAFT_DOMAIN,
        "status": (float(STATUS_DOMAIN[0]), float(STATUS_DOMAIN[1])),
    }

    for row in rows:
        result.rows_read += 1
        if progress is not None and result.rows_read % progress_every == 0:
            progress(result.rows_read)
        if limit is not None and result.rows_read > limit:
            result.rows_read -= 1
            break

        if len(row) != expected_width:
            result.rows_rejected += 1
            result.reject_reasons[RejectReason.WRONG_FIELD_COUNT.value] += 1
            continue

        # --- Column presence accounting (every column, before parsing) -----
        for name in header:
            stats = result.columns[name]
            if column(row, name).strip():
                stats.present += 1
            else:
                stats.empty += 1

        # --- Mandatory fields ---------------------------------------------
        raw_mmsi = column(row, "mmsi").strip()
        if not raw_mmsi:
            result.rows_rejected += 1
            result.reject_reasons[RejectReason.MISSING_MMSI.value] += 1
            continue

        raw_ts = column(row, "base_date_time").strip()
        try:
            timestamp = parse_timestamp(raw_ts)
        except RowRejectedError as exc:
            result.rows_rejected += 1
            result.reject_reasons[exc.reason.value] += 1
            result.columns["base_date_time"].malformed += 1
            continue

        raw_lon = column(row, "longitude").strip()
        raw_lat = column(row, "latitude").strip()
        if not raw_lon or not raw_lat:
            result.rows_rejected += 1
            result.reject_reasons[RejectReason.MISSING_COORDINATE.value] += 1
            continue
        try:
            longitude = float(raw_lon)
        except ValueError:
            result.invalid_longitude += 1
            result.columns["longitude"].malformed += 1
            result.rows_rejected += 1
            result.reject_reasons[RejectReason.INVALID_COORDINATE.value] += 1
            continue
        try:
            latitude = float(raw_lat)
        except ValueError:
            result.invalid_latitude += 1
            result.columns["latitude"].malformed += 1
            result.rows_rejected += 1
            result.reject_reasons[RejectReason.INVALID_COORDINATE.value] += 1
            continue

        out_of_range = False
        if not (MIN_LONGITUDE <= longitude <= MAX_LONGITUDE):
            result.invalid_longitude += 1
            result.columns["longitude"].out_of_domain += 1
            out_of_range = True
        if not (MIN_LATITUDE <= latitude <= MAX_LATITUDE):
            result.invalid_latitude += 1
            result.columns["latitude"].out_of_domain += 1
            out_of_range = True
        if out_of_range:
            result.rows_rejected += 1
            result.reject_reasons[RejectReason.COORDINATE_OUT_OF_RANGE.value] += 1
            continue

        result.rows_valid += 1

        # --- Identity ------------------------------------------------------
        mmsi_id = mmsi_ids.get(raw_mmsi)
        if mmsi_id is None:
            mmsi_id = len(mmsi_ids)
            mmsi_ids[raw_mmsi] = mmsi_id
            result.mmsi_length_distribution[len(raw_mmsi)] += 1
            result.mmsi_leading_digit_distribution[raw_mmsi[0] if raw_mmsi else "?"] += 1
        observations[mmsi_id] += 1

        ts_id = ts_ids.get(raw_ts)
        if ts_id is None:
            ts_id = len(ts_ids)
            ts_ids[raw_ts] = ts_id

        transceiver = column(row, "transceiver").strip().upper()
        tx_id = tx_ids.get(transceiver)
        if tx_id is None:
            tx_id = len(tx_ids)
            tx_ids[transceiver] = tx_id
        result.transceiver_counts[transceiver or "(empty)"] += 1

        # --- Uniqueness hypotheses ----------------------------------------
        key = (mmsi_id << _TS_ID_BITS) | ts_id
        packed_position = (
            ((round(longitude * _COORD_SCALE) + _LON_OFFSET) << _LON_SHIFT)
            | ((round(latitude * _COORD_SCALE) + _LAT_OFFSET) << _LAT_SHIFT)
            | tx_id
        )
        previous = seen_positions.get(key)
        if previous is None:
            seen_positions[key] = packed_position
        else:
            result.duplicate_mmsi_timestamp_pairs += 1
            if previous == packed_position:
                result.exact_duplicate_rows += 1
            else:
                result.conflicting_mmsi_timestamp_rows += 1

        # --- Time ----------------------------------------------------------
        iso = timestamp.isoformat()
        if result.timestamp_min is None or iso < result.timestamp_min:
            result.timestamp_min = iso
        if result.timestamp_max is None or iso > result.timestamp_max:
            result.timestamp_max = iso
        result.rows_by_hour[timestamp.hour] += 1

        # --- Space ---------------------------------------------------------
        if result.longitude_min is None or longitude < result.longitude_min:
            result.longitude_min = longitude
        if result.longitude_max is None or longitude > result.longitude_max:
            result.longitude_max = longitude
        if result.latitude_min is None or latitude < result.latitude_min:
            result.latitude_min = latitude
        if result.latitude_max is None or latitude > result.latitude_max:
            result.latitude_max = latitude
        if longitude == 0.0 and latitude == 0.0:
            result.null_island_rows += 1

        # --- Optional numeric fields --------------------------------------
        for name, (low, high) in numeric_domains.items():
            raw = column(row, name).strip()
            if not raw:
                continue
            try:
                value = float(raw)
            except ValueError:
                result.columns[name].malformed += 1
                continue
            if not (low <= value <= high):
                result.columns[name].out_of_domain += 1
            if name == "sog":
                result.sog_histogram[_sog_bucket(value)] += 1
                if result.sog_min is None or value < result.sog_min:
                    result.sog_min = value
                if result.sog_max is None or value > result.sog_max:
                    result.sog_max = value
            elif name == "status":
                result.status_counts[int(value)] += 1

        raw_type = column(row, "vessel_type").strip()
        if raw_type:
            try:
                vessel_type = int(float(raw_type))
            except ValueError:
                result.columns["vessel_type"].malformed += 1
            else:
                result.vessel_type_counts[vessel_type] += 1
                vessel_type_by_mmsi[mmsi_id] = vessel_type

        # --- Metadata churn per vessel ------------------------------------
        name_value = column(row, "vessel_name").strip()
        imo_value = normalize_imo(column(row, "imo"))
        call_sign_value = column(row, "call_sign").strip()

        if name_value:
            names.add(name_value)
            vessels_with_name.add(mmsi_id)
            vessel_display_name.setdefault(mmsi_id, name_value)
        if imo_value:
            imos.add(imo_value)
            vessels_with_imo.add(mmsi_id)
        if call_sign_value:
            call_signs.add(call_sign_value)

        signature = hash(
            (
                name_value,
                imo_value,
                call_sign_value,
                raw_type,
                column(row, "length").strip(),
                column(row, "width").strip(),
                column(row, "draft").strip(),
                column(row, "cargo").strip(),
            )
        )
        seen_signature = metadata_signature.get(mmsi_id)
        if seen_signature is None:
            metadata_signature[mmsi_id] = signature
        elif seen_signature != signature:
            metadata_signature[mmsi_id] = signature
            metadata_changes[mmsi_id] += 1

    # --- Roll-up -----------------------------------------------------------
    result.unique_mmsi = len(mmsi_ids)
    result.distinct_timestamps = len(ts_ids)
    result.unique_vessel_names = len(names)
    result.unique_imo = len(imos)
    result.unique_call_signs = len(call_signs)
    result.vessels_with_name = len(vessels_with_name)
    result.vessels_with_imo = len(vessels_with_imo)

    id_to_mmsi = {value: key for key, value in mmsi_ids.items()}
    result.top_vessels_by_observations = [
        {
            "mmsi": id_to_mmsi[mmsi_id],
            "name": vessel_display_name.get(mmsi_id),
            "vessel_type": vessel_type_by_mmsi.get(mmsi_id),
            "vessel_type_label": describe_vessel_type(vessel_type_by_mmsi.get(mmsi_id)).label,
            "observations": count,
        }
        for mmsi_id, count in observations.most_common(top_vessels)
    ]
    result.observations_per_vessel_percentiles = _percentiles(sorted(observations.values()))

    result.vessels_with_metadata_changes = len(metadata_changes)
    result.total_metadata_changes = sum(metadata_changes.values())
    result.max_metadata_changes_for_one_vessel = max(metadata_changes.values(), default=0)

    result.duration_seconds = time.perf_counter() - started
    if result.duration_seconds > 0:
        result.rows_per_second = result.rows_read / result.duration_seconds
    return result


def render_markdown(result: ProfileResult, *, generated_at: datetime) -> str:
    """Render a profile as a human-readable Markdown report.

    Every number here comes from :func:`profile_csv`. Nothing is estimated.
    """
    data = result.to_dict()
    rows = data["rows"]
    lines: list[str] = [
        "# AIS Dataset Profile",
        "",
        "Generated by `navisight-data profile`. Every figure below was measured by a",
        "single streaming pass over the source file — none are estimated.",
        "",
        f"- **Source file:** `{Path(result.source_path).name}`",
        f"- **Size:** {result.source_bytes:,} bytes ({result.source_bytes / 1024**3:.2f} GiB)",
        f"- **Profiled at:** {generated_at.isoformat()}",
        f"- **Pass duration:** {result.duration_seconds:.1f} s "
        f"({result.rows_per_second:,.0f} rows/s)",
        f"- **Schema matches documented 2025+ layout:** "
        f"{'yes' if result.header_matches_expected else 'NO — see header below'}",
        "",
        "## Rows",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Data rows read | {rows['read']:,} |",
        f"| Valid position events | {rows['valid']:,} |",
        f"| Rejected | {rows['rejected']:,} ({rows['rejected_pct']}%) |",
        "",
    ]

    if rows["reject_reasons"]:
        lines += ["**Rejection reasons**", "", "| Reason | Rows |", "|---|---|"]
        lines += [f"| `{k}` | {v:,} |" for k, v in rows["reject_reasons"].items()]
        lines.append("")
    else:
        lines += ["No row was rejected.", ""]

    uniq = data["uniqueness"]
    lines += [
        "## Uniqueness — which fields identify an observation",
        "",
        "This decides the ingestion fingerprint, and therefore whether re-running an",
        "import is idempotent. It is measured exactly (dense integer keys, no hashing),",
        "so these counts carry no collision caveat.",
        "",
        "| Hypothesis | Result |",
        "|---|---|",
        f"| `(mmsi, timestamp)` is unique | "
        f"**{'yes' if uniq['mmsi_timestamp_is_unique'] else 'no'}** |",
        f"| Rows repeating an `(mmsi, timestamp)` | {uniq['duplicate_mmsi_timestamp_pairs']:,} |",
        f"| …of those, identical position + transceiver (true duplicates) | "
        f"{uniq['exact_duplicate_rows']:,} |",
        f"| …of those, **different** position (genuine sub-second events) | "
        f"{uniq['conflicting_mmsi_timestamp_rows']:,} |",
        f"| `(mmsi, timestamp, lon, lat, transceiver)` is unique | "
        f"**{'yes' if uniq['mmsi_timestamp_position_transceiver_is_unique'] else 'no'}** |",
        "",
        "## Identity",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Distinct MMSIs (vessels) | {data['identity']['unique_mmsi']:,} |",
        f"| Vessels broadcasting a name | {data['identity']['vessels_with_name']:,} |",
        f"| Vessels broadcasting an IMO | {data['identity']['vessels_with_imo']:,} |",
        f"| Distinct vessel names | {data['identity']['unique_vessel_names']:,} |",
        f"| Distinct IMO numbers | {data['identity']['unique_imo']:,} |",
        f"| Distinct call signs | {data['identity']['unique_call_signs']:,} |",
        "",
        f"MMSI length distribution: `{data['identity']['mmsi_length_distribution']}`",
        "",
        "## Time (UTC)",
        "",
        f"- Earliest observation: `{data['time']['min']}`",
        f"- Latest observation: `{data['time']['max']}`",
        f"- Distinct timestamps: {data['time']['distinct_timestamps']:,}",
        "",
        "## Space",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Longitude range | {data['space']['longitude_min']} … "
        f"{data['space']['longitude_max']} |",
        f"| Latitude range | {data['space']['latitude_min']} … {data['space']['latitude_max']} |",
        f"| Invalid longitude | {data['space']['invalid_longitude']:,} |",
        f"| Invalid latitude | {data['space']['invalid_latitude']:,} |",
        f"| Rows at exactly (0, 0) | {data['space']['null_island_rows']:,} |",
        "",
        "## Column completeness",
        "",
        "`missing` counts rows where the column was blank. `malformed` means non-empty",
        "but unparseable. `out of domain` means parsed but outside the range the data",
        "dictionary documents — reported, never silently clamped.",
        "",
        "| Column | Present | Missing | Missing % | Malformed | Out of domain |",
        "|---|---|---|---|---|---|",
    ]
    for name, stats in data["columns"].items():
        lines.append(
            f"| `{name}` | {stats['present']:,} | {stats['empty']:,} | "
            f"{stats['missing_pct']}% | {stats['malformed']:,} | {stats['out_of_domain']:,} |"
        )

    lines += [
        "",
        "## Distributions",
        "",
        "**Transceiver class**",
        "",
        "| Class | Rows |",
        "|---|---|",
    ]
    lines += [f"| `{k}` | {v:,} |" for k, v in data["distributions"]["transceiver"].items()]

    lines += ["", "**Top vessel types**", "", "| Code | Label | Rows |", "|---|---|---|"]
    labels = data["distributions"]["vessel_type_labels"]
    for code, count in list(data["distributions"]["vessel_type"].items())[:15]:
        lines.append(f"| {code} | {labels.get(code, '—')} | {count:,} |")

    lines += ["", "**Navigational status**", "", "| Code | Rows |", "|---|---|"]
    lines += [f"| {k} | {v:,} |" for k, v in data["distributions"]["status"].items()]

    lines += ["", "**Speed over ground (knots)**", "", "| Bucket | Rows |", "|---|---|"]
    lines += [f"| {k} | {v:,} |" for k, v in data["distributions"]["sog_knots_histogram"].items()]

    per_vessel = data["per_vessel"]
    lines += [
        "",
        "## Per-vessel activity",
        "",
        f"Observations per vessel: `{per_vessel['observations_percentiles']}`",
        "",
        f"- Vessels whose broadcast metadata changed during the period: "
        f"{per_vessel['vessels_with_metadata_changes']:,}",
        f"- Total metadata changes observed: {per_vessel['total_metadata_changes']:,}",
        f"- Most changes for a single vessel: "
        f"{per_vessel['max_metadata_changes_for_one_vessel']:,}",
        "",
        "**Busiest vessels by observation count**",
        "",
        "| MMSI | Name | Type | Observations |",
        "|---|---|---|---|",
    ]
    for vessel in per_vessel["top_by_observations"]:
        lines.append(
            f"| `{vessel['mmsi']}` | {vessel['name'] or '—'} | "
            f"{vessel['vessel_type_label']} | {vessel['observations']:,} |"
        )

    lines += [
        "",
        "## How these numbers are used",
        "",
        "- The uniqueness result determines the ingestion fingerprint in",
        "  `app/domain/ais.py`, and therefore idempotency.",
        "- The distinct-MMSI count determines whether vessel metadata can be",
        "  accumulated in memory during ingestion (see `docs/data/AIS_PIPELINE.md`).",
        "- Column completeness determines which fields the UI must render as",
        "  “not reported” rather than assuming presence.",
        "- The time and space ranges bound the default map viewport and the",
        "  historical replay window.",
        "",
    ]
    return "\n".join(lines)
