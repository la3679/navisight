# Architecture Decision Records

Decisions that were non-obvious, hard to reverse, or that a future reader would
otherwise re-litigate. Each records the context, the decision, the alternatives
actually rejected, and the costs actually accepted.

Per [`CONTRIBUTING.md`](../../CONTRIBUTING.md), an ADR that lists no downside is
not finished.

| # | Decision | Status |
|---|---|---|
| [0001](0001-use-mongodb-for-geospatial-event-storage.md) | Use MongoDB for geospatial AIS event storage | Accepted |
| [0002](0002-separate-vessel-metadata-from-position-history.md) | Separate vessel metadata from position history | Accepted |
| [0003](0003-maintain-materialized-latest-vessel-state.md) | Maintain a materialized `vessel_latest` collection | Accepted |
| [0005](0005-accumulate-vessel-metadata-in-memory-during-ingestion.md) | Accumulate vessel metadata in memory during ingestion | Accepted |
| [0006](0006-deterministic-event-fingerprint-for-idempotency.md) | Deterministic event fingerprint as `_id` for idempotency | Accepted |
| [0007](0007-keep-large-ais-data-out-of-git.md) | Keep the raw AIS dataset out of Git | Accepted |
| [0008](0008-use-historical-replay-not-live-simulation.md) | Present data as historical replay, never live tracking | Accepted |
| [0009](0009-treat-source-timestamps-as-utc.md) | Treat source timestamps as UTC and store UTC internally | Accepted |
| [0010](0010-serve-the-maplibre-worker-from-our-own-origin.md) | Serve MapLibre's Web Worker from our own `public/` directory | Accepted |

Number 0004 and 0011+ are reserved for further frontend, 3D, and AI decisions
recorded as those subsystems land.

## Evidence

Several of these rest on numbers measured by `navisight-data profile` over the
real dataset, recorded in [`../data/AIS_PROFILE.md`](../data/AIS_PROFILE.md).
Where an ADR cites a figure, it comes from that report — not from an estimate.
