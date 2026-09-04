"""Streaming, resumable, idempotent AIS ingestion.

Design constraints, all from SOUL.md §6:

* **Streaming.** The 0.56 GiB source is never loaded whole; rows are parsed one
  at a time and written in bounded batches.
* **Idempotent.** Position ``_id`` is a deterministic fingerprint (ADR-0006), so
  re-inserting a row is a duplicate-key no-op rather than a second document.
* **Resumable.** A checkpoint row is recorded per batch. A crash between the
  insert and the checkpoint write is safe precisely *because* the insert is
  idempotent — the replayed rows collide and no-op.
* **Observable.** Rejections are counted by reason, never silently dropped.
* **Cancellable.** Ctrl+C finishes the current batch, writes a checkpoint, and
  marks the run cancelled.

The materialized ``vessel_latest`` update is the subtle part. The source file is
**not chronologically ordered** (measured: the first 50k rows already span
00:00 to 18:58 UTC), so "last write wins" would be wrong. See
:func:`build_latest_update`.
"""

from __future__ import annotations

import csv
import hashlib
import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bson import Binary
from pymongo import InsertOne, UpdateOne
from pymongo.database import Database
from pymongo.errors import BulkWriteError

from app.db import collections
from app.domain.ais import (
    EXPECTED_COLUMNS,
    AisRecord,
    RowRejectedError,
    VesselMetadata,
    parse_row,
)

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 5_000

#: Rows between durable checkpoints, and the window over which vessel_latest
#: updates are collapsed. Trades crash-replay work against write volume.
DEFAULT_CHECKPOINT_ROWS = 250_000
_DUPLICATE_KEY_ERROR = 11000
_CHECKSUM_CHUNK = 1 << 20

#: Schema version stamped on ingestion runs, so a future model change can be
#: distinguished from a re-import under the same model.
SCHEMA_VERSION = 1


@dataclass
class IngestionStats:
    """Counters for one ingestion run. Every number is reconciled at the end."""

    rows_read: int = 0
    rows_valid: int = 0
    rows_rejected: int = 0
    rows_skipped_resume: int = 0
    positions_inserted: int = 0
    positions_duplicate: int = 0
    vessels_upserted: int = 0
    latest_updated: int = 0
    reject_reasons: dict[str, int] = field(default_factory=dict)
    batches: int = 0
    duration_seconds: float = 0.0

    @property
    def rows_per_second(self) -> float:
        return self.rows_read / self.duration_seconds if self.duration_seconds > 0 else 0.0

    def record_rejection(self, reason: str) -> None:
        self.rows_rejected += 1
        self.reject_reasons[reason] = self.reject_reasons.get(reason, 0) + 1

    def as_document(self) -> dict[str, Any]:
        """Serializable form stored on the ingestion run document."""
        return {
            "rowsRead": self.rows_read,
            "rowsValid": self.rows_valid,
            "rowsRejected": self.rows_rejected,
            "rowsSkippedOnResume": self.rows_skipped_resume,
            "positionsInserted": self.positions_inserted,
            "positionsDuplicate": self.positions_duplicate,
            "vesselsUpserted": self.vessels_upserted,
            "latestUpdated": self.latest_updated,
            "rejectReasons": dict(self.reject_reasons),
            "batches": self.batches,
            "durationSeconds": round(self.duration_seconds, 3),
            "rowsPerSecond": round(self.rows_per_second, 1),
        }


class VesselAccumulator:
    """Latest non-empty metadata seen for one vessel, plus its activity window.

    Holding this in memory is safe because the bound is the *vessel* count
    (16,294 measured), not the row count — see ADR-0005.

    "Latest non-empty wins" is deliberate: 371 vessels changed metadata during
    the profiled day and some broadcasts carry blanks. A blank must not erase a
    value we already have, and we do not attempt to adjudicate which conflicting
    broadcast was correct.
    """

    __slots__ = (
        "call_sign",
        "cargo",
        "draft",
        "first_seen",
        "imo",
        "last_metadata_at",
        "last_seen",
        "length",
        "name",
        "vessel_type",
        "width",
    )

    def __init__(self) -> None:
        self.name: str | None = None
        self.imo: str | None = None
        self.call_sign: str | None = None
        self.vessel_type: int | None = None
        self.length: int | None = None
        self.width: int | None = None
        self.draft: float | None = None
        self.cargo: int | None = None
        self.first_seen: datetime | None = None
        self.last_seen: datetime | None = None
        self.last_metadata_at: datetime | None = None

    def observe(self, timestamp: datetime, metadata: VesselMetadata) -> None:
        """Fold one observation in, tracking the activity window and metadata."""
        if self.first_seen is None or timestamp < self.first_seen:
            self.first_seen = timestamp
        if self.last_seen is None or timestamp > self.last_seen:
            self.last_seen = timestamp

        if metadata.is_empty:
            return
        # Only accept a field from a broadcast at least as new as the one that
        # set it, so out-of-order rows cannot overwrite newer metadata.
        if self.last_metadata_at is not None and timestamp < self.last_metadata_at:
            return
        self.last_metadata_at = timestamp
        for attribute in (
            "name",
            "imo",
            "call_sign",
            "vessel_type",
            "length",
            "width",
            "draft",
            "cargo",
        ):
            value = getattr(metadata, attribute)
            if value is not None:
                setattr(self, attribute, value)

    def as_update(self, mmsi: str) -> UpdateOne:
        """Bulk upsert for the ``vessels`` collection.

        ``$min``/``$max`` on the activity window make this safe to apply in any
        order and safe to re-apply — a resumed run cannot narrow a window it
        previously widened.
        """
        fields: dict[str, Any] = {"mmsi": mmsi}
        if self.name is not None:
            fields["name"] = self.name
            # Uppercased copy so an anchored prefix regex can use an index
            # without a case-insensitive collation scan (see db/indexes.py).
            fields["nameNormalized"] = self.name.upper()
        if self.imo is not None:
            fields["imo"] = self.imo
        if self.call_sign is not None:
            fields["callSign"] = self.call_sign
        if self.vessel_type is not None:
            fields["vesselType"] = self.vessel_type
        if self.cargo is not None:
            fields["cargo"] = self.cargo

        dimensions = {
            key: value
            for key, value in (
                ("lengthMeters", self.length),
                ("widthMeters", self.width),
                ("draftMeters", self.draft),
            )
            if value is not None
        }
        if dimensions:
            fields["dimensions"] = dimensions
        if self.last_metadata_at is not None:
            fields["metadataUpdatedAt"] = self.last_metadata_at

        update: dict[str, Any] = {"$set": fields}
        if self.first_seen is not None:
            update["$min"] = {"firstSeenAt": self.first_seen}
        if self.last_seen is not None:
            update["$max"] = {"lastSeenAt": self.last_seen}
        return UpdateOne({"_id": mmsi}, update, upsert=True)


def build_position_document(record: AisRecord, *, dataset: str, source_file: str) -> dict[str, Any]:
    """Build one ``vessel_positions`` document.

    Absent values are **omitted** rather than stored as ``null``: it keeps
    "missing" represented exactly one way, and across 5.9M documents where
    heading is absent 50.6% of the time it is a meaningful storage saving.

    Vessel name, IMO, dimensions and type are deliberately *not* here — they
    live once per vessel in ``vessels`` (ADR-0002).
    """
    navigation = {
        key: value
        for key, value in (
            ("speedOverGroundKnots", record.sog),
            ("courseOverGroundDegrees", record.cog),
            ("headingDegrees", record.heading),
            ("status", record.status),
        )
        if value is not None
    }
    source: dict[str, Any] = {"dataset": dataset, "file": source_file}
    if record.transceiver is not None:
        source["transceiver"] = record.transceiver

    document: dict[str, Any] = {
        "_id": Binary(record.fingerprint()),
        "mmsi": record.mmsi,
        "timestamp": record.timestamp,
        # GeoJSON order is [longitude, latitude]. Always. (SOUL.md §7)
        "location": {"type": "Point", "coordinates": [record.longitude, record.latitude]},
        "source": source,
    }
    if navigation:
        document["navigation"] = navigation
    return document


def build_latest_update(record: AisRecord) -> UpdateOne:
    """Conditionally materialize newest-known state for a vessel.

    **This is the out-of-order guard.** The source is not chronologically
    ordered, so the update must compare event times, not arrival order.

    It uses an aggregation-pipeline update that replaces the whole document only
    when the incoming observation is newer. The obvious alternative —
    ``updateOne({_id: mmsi, timestamp: {$lt: new}}, ..., upsert=True)`` — is a
    trap: when a *newer* document already exists the filter matches nothing, so
    the upsert attempts an insert and fails with a duplicate key error on every
    stale row. The pipeline form is a clean no-op instead.

    On upsert, ``$$ROOT`` is just ``{_id: mmsi}`` from the filter, so
    ``$timestamp`` is missing and the new document is written.
    """
    replacement: dict[str, Any] = {
        "_id": record.mmsi,
        "mmsi": record.mmsi,
        "timestamp": record.timestamp,
        "location": {"type": "Point", "coordinates": [record.longitude, record.latitude]},
    }
    replacement.update(
        {
            key: value
            for key, value in (
                ("speedOverGroundKnots", record.sog),
                ("courseOverGroundDegrees", record.cog),
                ("headingDegrees", record.heading),
                ("status", record.status),
                ("name", record.metadata.name),
                ("vesselType", record.metadata.vessel_type),
                ("transceiverClass", record.transceiver),
            )
            if value is not None
        }
    )

    return UpdateOne(
        {"_id": record.mmsi},
        [
            {
                "$replaceWith": {
                    "$cond": [
                        {
                            "$or": [
                                {"$eq": [{"$type": "$timestamp"}, "missing"]},
                                {"$lt": ["$timestamp", record.timestamp]},
                            ]
                        },
                        replacement,
                        "$$ROOT",
                    ]
                }
            }
        ],
        upsert=True,
    )


def file_checksum(path: Path, *, progress: Callable[[int], None] | None = None) -> str:
    """BLAKE2b digest of the source file.

    Identifies the exact file a run consumed, so ``--resume`` can refuse to
    continue a checkpoint that belongs to different data.
    """
    digest = hashlib.blake2b(digest_size=16)
    read = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_CHECKSUM_CHUNK):
            digest.update(chunk)
            read += len(chunk)
            if progress is not None:
                progress(read)
    return digest.hexdigest()


def _iter_source_rows(path: Path) -> Iterator[dict[str, str]]:
    """Stream the CSV as dicts keyed by the header's column names."""
    with path.open("r", encoding="utf-8", newline="", errors="replace", buffering=1 << 20) as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"{path} is empty") from exc
        if header and header[0].startswith("﻿"):
            header[0] = header[0].lstrip("﻿")
        header = [column.strip().lower() for column in header]
        if tuple(header) != EXPECTED_COLUMNS:
            logger.warning(
                "Source header differs from the documented 2025+ schema; "
                "parsing by column name. header=%s",
                header,
            )
        width = len(header)
        for row in reader:
            if len(row) != width:
                yield {}  # signalled to the caller as a wrong-field-count rejection
                continue
            yield dict(zip(header, row, strict=True))


def _flush_positions(
    database: Database[dict[str, Any]],
    operations: list[InsertOne[dict[str, Any]]],
    stats: IngestionStats,
) -> None:
    """Insert a batch, treating duplicate keys as expected no-ops.

    Unordered so one duplicate does not abort the rest of the batch. A
    duplicate here is not an error: it is idempotency working (ADR-0006).
    """
    if not operations:
        return
    try:
        result = database[collections.VESSEL_POSITIONS].bulk_write(operations, ordered=False)
        stats.positions_inserted += result.inserted_count
    except BulkWriteError as exc:
        write_errors = exc.details.get("writeErrors", []) if exc.details else []
        duplicates = sum(1 for error in write_errors if error.get("code") == _DUPLICATE_KEY_ERROR)
        others = [error for error in write_errors if error.get("code") != _DUPLICATE_KEY_ERROR]
        if others:
            # Anything that is not a duplicate key is a real failure and must
            # not be swallowed (SOUL.md §5).
            raise
        stats.positions_duplicate += duplicates
        inserted = exc.details.get("nInserted", 0) if exc.details else 0
        stats.positions_inserted += inserted


def ingest(
    path: Path,
    database: Database[dict[str, Any]],
    *,
    dataset: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: int | None = None,
    resume_from_row: int = 0,
    dry_run: bool = False,
    run_id: Any = None,
    checkpoint_rows: int = DEFAULT_CHECKPOINT_ROWS,
    progress: Callable[[IngestionStats], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> IngestionStats:
    """Ingest an AIS CSV into MongoDB.

    Args:
        path: Source CSV, opened read-only and never modified.
        database: Target database.
        dataset: Provenance label stored on each position document.
        batch_size: Operations per bulk write.
        limit: Stop after this many data rows (counted from the file start).
        resume_from_row: Skip this many data rows before ingesting.
        dry_run: Parse and count, but perform no writes.
        run_id: ``ingestion_runs`` document id to checkpoint against.
        checkpoint_rows: Rows between durable checkpoints. Also the window over
            which vessel_latest updates are collapsed, so larger is faster but
            replays more work after a crash.
        progress: Called with live stats after each position batch.
        should_cancel: Polled between batches; truthy value stops cleanly.

    Returns:
        :class:`IngestionStats` with every counter reconciled.
    """
    stats = IngestionStats()
    started = time.perf_counter()
    source_file = path.name

    position_ops: list[InsertOne[dict[str, Any]]] = []
    # Newest observation per vessel since the last latest-state flush. Collapsing
    # here is what makes ingestion fast: measured on 20k rows, per-row
    # vessel_latest updates cost 5.46 s against 0.26 s for the position inserts
    # — 95% of write time. Because distinct vessels saturate at ~16k while rows
    # keep growing, a larger accumulation window collapses proportionally more
    # (see docs/performance/BENCHMARKS.md).
    latest_pending: dict[str, AisRecord] = {}
    vessels: dict[str, VesselAccumulator] = {}
    runs = database[collections.INGESTION_RUNS]

    def flush_positions() -> None:
        """Write pending position inserts."""
        if dry_run:
            position_ops.clear()
            return
        _flush_positions(database, position_ops, stats)
        position_ops.clear()
        stats.batches += 1

    def checkpoint(*, final: bool = False) -> None:
        """Flush everything durable, then advance the resume checkpoint.

        Ordering matters. Positions and latest state are written *before* the
        checkpoint row is recorded, so a crash in between replays rows that are
        already stored — which idempotency turns into a no-op (ADR-0006). The
        reverse order could skip data permanently.
        """
        flush_positions()
        if latest_pending and not dry_run:
            result = database[collections.VESSEL_LATEST].bulk_write(
                [build_latest_update(record) for record in latest_pending.values()],
                ordered=False,
            )
            stats.latest_updated += result.modified_count + result.upserted_count
        latest_pending.clear()
        if run_id is not None and not dry_run:
            runs.update_one(
                {"_id": run_id},
                {
                    "$set": {
                        "lastCheckpointRow": stats.rows_read,
                        "updatedAt": datetime.now(UTC),
                        "stats": stats.as_document(),
                        **({"status": "running"} if not final else {}),
                    }
                },
            )

    for row in _iter_source_rows(path):
        stats.rows_read += 1

        if stats.rows_read <= resume_from_row:
            stats.rows_skipped_resume += 1
            continue
        if limit is not None and stats.rows_read > limit:
            stats.rows_read -= 1
            break

        if not row:
            stats.record_rejection("wrong_field_count")
            continue

        try:
            record = parse_row(row)
        except RowRejectedError as exc:
            stats.record_rejection(exc.reason.value)
            continue

        stats.rows_valid += 1
        position_ops.append(
            InsertOne(build_position_document(record, dataset=dataset, source_file=source_file))
        )

        # Keep only the chronologically newest observation per vessel. The
        # source is not time-ordered, so this compares event times rather than
        # relying on arrival order (ADR-0003).
        seen = latest_pending.get(record.mmsi)
        if seen is None or record.timestamp > seen.timestamp:
            latest_pending[record.mmsi] = record

        vessels.setdefault(record.mmsi, VesselAccumulator()).observe(
            record.timestamp, record.metadata
        )

        if len(position_ops) >= batch_size:
            flush_positions()
            stats.duration_seconds = time.perf_counter() - started
            if progress is not None:
                progress(stats)
            if should_cancel is not None and should_cancel():
                logger.info("Ingestion cancelled at row %d", stats.rows_read)
                break

        if stats.rows_read % checkpoint_rows == 0:
            checkpoint()

    checkpoint(final=True)

    # Vessel metadata is written once at the end from the in-memory accumulator
    # (ADR-0005): ~16k upserts instead of ~5.9M.
    if vessels and not dry_run:
        updates = [accumulator.as_update(mmsi) for mmsi, accumulator in vessels.items()]
        for start in range(0, len(updates), batch_size):
            result = database[collections.VESSELS].bulk_write(
                updates[start : start + batch_size], ordered=False
            )
            stats.vessels_upserted += result.upserted_count + result.modified_count

    stats.duration_seconds = time.perf_counter() - started
    return stats
