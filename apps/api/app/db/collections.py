"""Collection names and the document shapes NaviSight stores.

Names are constants rather than string literals scattered through the codebase,
so a rename is a single edit and a typo is an import error rather than a
silently-empty query.

The data model and the reasoning behind it live in
``docs/database/DATA_MODEL.md``; the short version is that vessel identity
(16,294 documents, slow-changing) is separated from position events (5.9M
documents, append-only), with a small materialized current-state collection
serving the map. See ADR-0002 and ADR-0003.
"""

from __future__ import annotations

from typing import Final

#: One document per MMSI: identity and slow-changing metadata.
VESSELS: Final = "vessels"

#: One document per observation. ``_id`` is the deterministic event
#: fingerprint (ADR-0006), which is what makes ingestion idempotent.
VESSEL_POSITIONS: Final = "vessel_positions"

#: Materialized newest-known state per vessel, for the operations map.
VESSEL_LATEST: Final = "vessel_latest"

#: Ingestion lifecycle: checkpoints, counts, throughput, outcomes.
INGESTION_RUNS: Final = "ingestion_runs"

#: Agent execution traces. Tool calls and timings only — never hidden
#: reasoning (SOUL.md §8, and docs/ai/AI_SAFETY.md).
AGENT_RUNS: Final = "agent_runs"

#: Optional port reference data. Absent until explicitly loaded; port features
#: degrade to a "not configured" state rather than failing.
PORTS: Final = "ports"

#: Precomputed whole-archive analytics. Derived data: rebuilt from
#: ``vessel_positions`` by ``navisight-data rollup`` and safe to drop. See
#: ``app/services/rollup.py`` for the measurement that justifies it.
ANALYTICS_ROLLUP: Final = "analytics_rollup"

ALL_COLLECTIONS: Final[tuple[str, ...]] = (
    VESSELS,
    VESSEL_POSITIONS,
    VESSEL_LATEST,
    INGESTION_RUNS,
    AGENT_RUNS,
    PORTS,
    ANALYTICS_ROLLUP,
)

#: Collections the AIS import writes to. `navisight-data reset` clears exactly
#: these, leaving ports and agent traces alone. The rollup is included because
#: it is derived from them: leaving it behind after a reset would strand a
#: summary of data that no longer exists.
AIS_COLLECTIONS: Final[tuple[str, ...]] = (
    VESSELS,
    VESSEL_POSITIONS,
    VESSEL_LATEST,
    ANALYTICS_ROLLUP,
)
