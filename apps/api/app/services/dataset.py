"""Dataset status and data-quality reporting.

These endpoints exist so the interface can be honest about what it is showing:
which file was imported, what period it covers, how complete it is, and what is
not configured. A UI that cannot say "no data yet" ends up implying it has some.
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from app.api import schemas
from app.config import REPO_ROOT, get_settings
from app.db import collections

_PROFILE_PATH = REPO_ROOT / "docs" / "data" / "ais_profile.json"


@lru_cache(maxsize=1)
def _load_profile() -> dict[str, Any] | None:
    """Read the committed profile report, if present.

    Cached: it is an immutable build artifact, not live state.
    """
    if not _PROFILE_PATH.exists():
        return None
    try:
        return json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
    except (OSError, ValueError):
        return None


async def _coverage_bounds(
    database: AsyncDatabase[dict[str, Any]],
) -> schemas.DatasetCoverage:
    """The archive's first and last timestamps, read from the index.

    Two sorted single-document reads rather than one ``$group`` with ``$min``
    and ``$max``. The aggregation is the obvious spelling and it is the wrong
    one here: ``$group`` has to visit every document to know the extremes, so
    it scanned all 5,928,519 and measured **4.634 s**. The pair below rides
    ``position_timestamp`` in each direction and examines **one index key
    each** — ``explain()`` reports ``totalKeysExamined: 1``,
    ``executionTimeMillis: 0`` — for **0.019 s** total, returning identical
    values.

    That matters out of proportion to the endpoint: the dataset badge in the
    header calls ``/dataset/status`` on every page, so this was 4.6 s of
    latency behind every screen in the product.
    """
    collection = database[collections.VESSEL_POSITIONS]
    first = await collection.find_one({}, {"timestamp": 1}, sort=[("timestamp", 1)])
    last = await collection.find_one({}, {"timestamp": 1}, sort=[("timestamp", -1)])
    if first is None or last is None:
        return schemas.DatasetCoverage()
    return schemas.DatasetCoverage(start=first["timestamp"], end=last["timestamp"])


async def get_status(database: AsyncDatabase[dict[str, Any]]) -> schemas.DatasetStatus:
    """Summarize what is loaded and what is configured."""
    settings = get_settings()

    positions = await database[collections.VESSEL_POSITIONS].estimated_document_count()
    vessels = await database[collections.VESSELS].estimated_document_count()
    latest = await database[collections.VESSEL_LATEST].estimated_document_count()
    ports = await database[collections.PORTS].estimated_document_count()

    coverage = schemas.DatasetCoverage()
    if positions:
        coverage = await _coverage_bounds(database)

    run = await database[collections.INGESTION_RUNS].find_one(sort=[("startedAt", -1)])
    summary: schemas.IngestionSummary | None = None
    if run is not None:
        stats = run.get("stats") or {}
        summary = schemas.IngestionSummary(
            status=run.get("status"),
            source_file=run.get("sourceFile"),
            started_at=run.get("startedAt"),
            completed_at=run.get("completedAt"),
            rows_read=stats.get("rowsRead"),
            positions_inserted=stats.get("positionsInserted"),
            positions_duplicate=stats.get("positionsDuplicate"),
            rows_rejected=stats.get("rowsRejected"),
        )

    return schemas.DatasetStatus(
        configured=settings.ais_data_path.exists(),
        has_data=positions > 0,
        dataset=settings.ais_dataset_name,
        counts=schemas.DatasetCounts(positions=positions, vessels=vessels, latest_states=latest),
        coverage=coverage,
        last_ingestion=summary,
        ports_configured=ports > 0,
        ai_configured=settings.ai_enabled,
    )


def get_data_quality() -> schemas.DataQualityResponse | None:
    """Field completeness, sourced from the committed profile report.

    Served from the profiler's output rather than recomputed: the numbers
    describe the *source file*, including rows that were rejected and therefore
    are not in the database at all. Recomputing from MongoDB would silently
    exclude exactly the records a data-quality view exists to surface.
    """
    profile = _load_profile()
    if profile is None:
        return None

    fields = [
        schemas.DataQualityField(
            field=name,
            present=stats["present"],
            missing=stats["empty"],
            missing_percent=stats["missing_pct"],
        )
        for name, stats in profile.get("columns", {}).items()
    ]
    generated_at_raw = profile.get("generated_at")
    return schemas.DataQualityResponse(
        source=Path(profile["source"]["path"]).name,
        rows_read=profile["rows"]["read"],
        rows_rejected=profile["rows"]["rejected"],
        exact_duplicates=profile["uniqueness"]["exact_duplicate_rows"],
        fields=fields,
        generated_at=datetime.fromisoformat(generated_at_raw) if generated_at_raw else None,
    )
