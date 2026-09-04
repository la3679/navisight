# ADR-0001: Use MongoDB for geospatial AIS event storage

- **Status:** Accepted
- **Date:** 2026-09-03

## Context

NaviSight stores ~5.9M AIS position observations per ingested day and must
serve four query shapes:

1. **Spatial** — which vessels are inside this map viewport, or within N km of
   this point, ordered by distance.
2. **Per-vessel time series** — this vessel's track between two timestamps,
   chronologically.
3. **Current state** — the latest known position of every vessel, for the map.
4. **Aggregate** — traffic by hour, vessel-type distribution, busiest vessels.

Profiling (`docs/data/AIS_PROFILE.md`) measured the shape of the data:

- 5,929,631 rows, 0 rejected, over a 24-hour period.
- Only **16,294 distinct vessels** — a very wide fan-out ratio of ~364
  observations per vessel.
- Records are **heterogeneously sparse**: `heading` is absent in 50.6% of rows,
  `imo` in 60.1%, `draft` in 44.3%, `status` in 35.4%, `cargo` in 33.1%.
- Coordinates span the antimeridian (−175.1 … +146.5 longitude).

## Decision

Use **MongoDB** as the primary datastore, with GeoJSON `Point` geometry and a
`2dsphere` index on position data.

## Alternatives considered

**PostgreSQL + PostGIS.** The strongest alternative, and better than MongoDB at
complex spatial joins and analytical SQL. Rejected because: the sparsity above
means a relational row would be substantially NULL columns or need an EAV/JSONB
side-table; the ingest path is append-only with no relational integrity needs
that would justify the extra schema-migration weight; and one of this project's
explicit goals is to demonstrate access-pattern-driven document modeling. This
is a real trade-off, not a dismissal — for heavy spatial analytics, PostGIS
would win.

**TimescaleDB / a dedicated time-series database.** Good fit for the per-vessel
time series, poor fit for query shapes 1 and 3, which are the product's centre
of gravity. Would force a second store for spatial work.

**MongoDB time-series collections.** Genuinely tempting for `vessel_positions`,
and a natural fit for `metaField: mmsi`. Rejected for now because they do not
support the unique `_id`-based idempotency this pipeline relies on (see
[ADR-0006](0006-deterministic-event-fingerprint-for-idempotency.md)) — a
time-series collection would push deduplication into application logic or a
post-import pass, trading away the strongest correctness property in the
system. Recorded as a future option in
[`docs/database/DATA_MODEL.md`](../database/DATA_MODEL.md) if the ingest
contract changes.

**Elasticsearch.** Rejected under SOUL.md §5 — it solves a search problem this
project does not have, and would be operational weight for its own sake.

## Consequences

**Accepted costs:**

- No SQL. Aggregations are expressed as pipelines, which are more verbose and
  harder to review than the equivalent SQL for the analytics queries.
- No foreign keys. Referential consistency between `vessels`, `vessel_latest`,
  and `vessel_positions` is maintained by the ingestion pipeline and verified
  by `navisight-data validate`, not by the database.
- `$geoNear` must be the first stage of an aggregation pipeline, which
  constrains how nearby-vessel queries can be composed.
- Antimeridian-crossing bounding boxes need explicit handling; a naive
  `$box` query on this dataset is wrong. Tracked as a correctness case with
  tests rather than left to chance.

**Benefits realised:**

- Sparse optional fields are simply absent rather than NULL columns, which
  matches the "missing is missing" rule in SOUL.md §6 directly.
- `2dsphere` covers both `$geoNear` (distance-sorted) and `$geoWithin`
  (containment) from one index.
- A single store serves all four query shapes.
