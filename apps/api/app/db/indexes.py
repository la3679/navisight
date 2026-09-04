"""Index definitions.

SOUL.md §7: *every index exists to serve a named query; an index nobody can name
a query for gets deleted.* That rule is enforced structurally here — an
:class:`IndexSpec` cannot be constructed without a ``serves`` description, and
``navisight-data indexes --explain`` prints them.

Write cost is real and stated. Each index on ``vessel_positions`` is an extra
5.9M-entry structure to build and maintain during import, so the list is
deliberately short.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pymongo
from pymongo.database import Database

from app.db import collections


@dataclass(frozen=True)
class IndexSpec:
    """One index, with the query that justifies it."""

    collection: str
    keys: list[tuple[str, Any]]
    name: str

    serves: str
    """The specific query this exists for. Required."""

    write_cost: str
    """What maintaining it costs on the ingest path."""

    unique: bool = False
    sparse: bool = False
    partial_filter: dict[str, Any] | None = None
    options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # MongoDB rejects an index declaring both. A partial filter is strictly
        # more expressive, so this is a definition error, not a runtime choice.
        if self.sparse and self.partial_filter is not None:
            raise ValueError(
                f"{self.name}: cannot combine sparse with partialFilterExpression; "
                "use the partial filter alone."
            )

    def as_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for ``create_index``."""
        kwargs: dict[str, Any] = {"name": self.name, **self.options}
        if self.unique:
            kwargs["unique"] = True
        if self.sparse:
            kwargs["sparse"] = True
        if self.partial_filter is not None:
            kwargs["partialFilterExpression"] = self.partial_filter
        return kwargs


INDEX_SPECS: tuple[IndexSpec, ...] = (
    # -----------------------------------------------------------------------
    # vessel_positions — 5.9M documents. Every index here is expensive.
    # -----------------------------------------------------------------------
    IndexSpec(
        collection=collections.VESSEL_POSITIONS,
        keys=[("location", pymongo.GEOSPHERE)],
        name="position_location_2dsphere",
        serves=(
            "Historical spatial search: GET /api/v1/geo/nearby with a time window, "
            "and the agent's find_vessels_near_location tool. Supports both "
            "$geoNear (distance-sorted) and $geoWithin (containment) from one index."
        ),
        write_cost=(
            "Highest of any index here: 2dsphere keys are more expensive to build "
            "than b-tree keys, across 5.9M documents. Justified because spatial "
            "search over history is a core product capability, not a nice-to-have."
        ),
    ),
    IndexSpec(
        collection=collections.VESSEL_POSITIONS,
        keys=[("mmsi", pymongo.ASCENDING), ("timestamp", pymongo.DESCENDING)],
        name="position_mmsi_timestamp",
        serves=(
            "Per-vessel history: GET /api/v1/vessels/{mmsi}/positions. The compound "
            "order matters — mmsi equality then timestamp range means the sort is "
            "satisfied by the index, so no in-memory sort and no blocking SORT stage. "
            "Also serves the trajectory endpoint and the vessel detail timeline."
        ),
        write_cost=(
            "One b-tree entry per position document. This is the index the product "
            "cannot function without: without it, one vessel's track is a 5.9M-document "
            "collection scan."
        ),
    ),
    IndexSpec(
        collection=collections.VESSEL_POSITIONS,
        keys=[("timestamp", pymongo.DESCENDING)],
        name="position_timestamp",
        serves=(
            "Time-window analytics across all vessels: GET /api/v1/analytics/traffic "
            "and /analytics/activity, which $match a sub-day range before grouping. "
            "Without it, a one-hour query scans all 5.9M documents to find ~250k."
        ),
        write_cost=(
            "One b-tree entry per position document. Kept under review: the current "
            "dataset is a single day, so a whole-day query gains nothing from it. "
            "docs/performance/BENCHMARKS.md records the measured effect on a "
            "sub-day range; if explain shows it unused in practice, it should be dropped."
        ),
    ),
    # -----------------------------------------------------------------------
    # vessel_latest — 16,294 documents. Cheap to index.
    # -----------------------------------------------------------------------
    IndexSpec(
        collection=collections.VESSEL_LATEST,
        keys=[("location", pymongo.GEOSPHERE)],
        name="latest_location_2dsphere",
        serves=(
            "The operations map's primary query: GET /api/v1/map/vessels for a "
            "viewport, and GET /api/v1/geo/nearby without a time filter. This is the "
            "index that replaces a 5.9M-document aggregation with a bounded lookup "
            "over 16k documents on every map pan (ADR-0003)."
        ),
        write_cost=(
            "Negligible: one entry per vessel, updated at most once per observation "
            "and only when the observation is newer than the stored one."
        ),
    ),
    IndexSpec(
        collection=collections.VESSEL_LATEST,
        keys=[("vesselType", pymongo.ASCENDING)],
        name="latest_vessel_type",
        serves=(
            "Map and analytics filtering by vessel type, and the vessel-type "
            "distribution aggregation over current state."
        ),
        write_cost=(
            "Negligible at 16k documents. Marginal value — a collection scan of 16k "
            "documents is already fast — so this is a candidate for removal if "
            "benchmarking shows no measurable difference."
        ),
    ),
    # -----------------------------------------------------------------------
    # vessels — 16,294 documents. Search-oriented.
    # -----------------------------------------------------------------------
    IndexSpec(
        collection=collections.VESSELS,
        keys=[("nameNormalized", pymongo.ASCENDING)],
        name="vessel_name_normalized",
        serves=(
            "Vessel search by name: GET /api/v1/vessels?q=. Uses an uppercased, "
            "trimmed field so a case-insensitive anchored prefix regex (/^QUERY/) "
            "can use the index. NOTE: this is prefix matching, not full-text search "
            "— it deliberately does not pretend a b-tree gives full-text semantics "
            "(SOUL.md §7). Substring and fuzzy matching would need Atlas Search or "
            "a dedicated text index; see docs/database/INDEXING.md."
        ),
        write_cost="Negligible: one entry per vessel, written once at import.",
    ),
    IndexSpec(
        collection=collections.VESSELS,
        keys=[("imo", pymongo.ASCENDING)],
        name="vessel_imo",
        serves="Vessel lookup by IMO number in search and in the agent's search_vessels tool.",
        write_cost=(
            "Negligible, and smaller than a full index: the partial filter indexes only "
            "the 5,103 vessels that actually broadcast an IMO (60.1% of rows have none)."
        ),
        partial_filter={"imo": {"$type": "string"}},
    ),
    IndexSpec(
        collection=collections.VESSELS,
        keys=[("callSign", pymongo.ASCENDING)],
        name="vessel_call_sign",
        serves="Vessel lookup by call sign in search.",
        write_cost=("Negligible. Partial-filtered to vessels that broadcast a call sign."),
        partial_filter={"callSign": {"$type": "string"}},
    ),
    # -----------------------------------------------------------------------
    # Operational collections
    # -----------------------------------------------------------------------
    IndexSpec(
        collection=collections.INGESTION_RUNS,
        keys=[("sourceChecksum", pymongo.ASCENDING), ("startedAt", pymongo.DESCENDING)],
        name="ingestion_source_started",
        serves=(
            "Resume: find the most recent run for this exact source file so "
            "--resume can continue from its checkpoint row."
        ),
        write_cost="Negligible: a handful of documents.",
    ),
    IndexSpec(
        collection=collections.INGESTION_RUNS,
        keys=[("status", pymongo.ASCENDING), ("startedAt", pymongo.DESCENDING)],
        name="ingestion_status_started",
        serves="GET /api/v1/dataset/status and `navisight-data status`.",
        write_cost="Negligible.",
    ),
    IndexSpec(
        collection=collections.AGENT_RUNS,
        keys=[("createdAt", pymongo.DESCENDING)],
        name="agent_created",
        serves="Recent agent runs for the copilot's trace view.",
        write_cost="Negligible.",
    ),
    IndexSpec(
        collection=collections.PORTS,
        keys=[("location", pymongo.GEOSPHERE)],
        name="port_location_2dsphere",
        serves=(
            "Nearest-port resolution for a vessel position, and port proximity "
            "queries. Only created when port reference data is loaded."
        ),
        write_cost="Negligible: a few thousand documents at most.",
    ),
)


def ensure_indexes(
    database: Database[dict[str, Any]],
    *,
    only: str | None = None,
) -> list[str]:
    """Create every declared index, returning the names created or confirmed.

    ``create_index`` is idempotent, so this is safe to run repeatedly. On
    ``vessel_positions`` it is far cheaper to run *before* a bulk import than
    after, because building a 2dsphere index over 5.9M existing documents is a
    long blocking operation.

    Args:
        database: Target database.
        only: Restrict to a single collection name.
    """
    created: list[str] = []
    for spec in INDEX_SPECS:
        if only is not None and spec.collection != only:
            continue
        name = database[spec.collection].create_index(spec.keys, **spec.as_kwargs())
        created.append(f"{spec.collection}.{name}")
    return created


def describe_indexes() -> list[dict[str, Any]]:
    """Every index with its justification, for docs and the CLI."""
    return [
        {
            "collection": spec.collection,
            "name": spec.name,
            "keys": [[field_name, direction] for field_name, direction in spec.keys],
            "unique": spec.unique,
            "sparse": spec.sparse,
            "serves": spec.serves,
            "write_cost": spec.write_cost,
        }
        for spec in INDEX_SPECS
    ]
