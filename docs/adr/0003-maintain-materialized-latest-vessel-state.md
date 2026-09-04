# ADR-0003: Maintain a materialized `vessel_latest` collection

- **Status:** Accepted
- **Date:** 2026-09-03

## Context

The operations map's primary query is: *"give me the most recent known position
of every vessel in this viewport."* Answering that from `vessel_positions`
means, for each of 16,294 vessels, finding the maximum timestamp — a
`$sort` + `$group` over 5.9M documents, or a `$group` with `$top`. Either way it
touches the entire collection on a query the user triggers on every map pan.

Profiling also established a fact that makes the naive approach dangerous:
**the source file is not chronologically ordered.** The first 50,000 rows
already span 00:00:00 to 18:58:42 UTC. Insertion order is therefore *not* event
order, and any "last write wins" strategy would produce a wrong answer.

## Decision

Maintain **`vessel_latest`**: one document per MMSI holding the chronologically
newest observation, with a small amount of denormalized metadata (name, vessel
type, transceiver class) so the map needs no join.

Updates are **conditional on event time**, never on arrival order:

```javascript
updateOne(
  { _id: mmsi, timestamp: { $lt: newTimestamp } },
  { $set: { ...newState } },
  { upsert: true }
)
```

An observation older than the stored one matches nothing and is a no-op.

## Alternatives considered

**Compute latest state on demand.** Correct but slow, and the cost is paid on
the most latency-sensitive interaction in the product. Rejected.

**A MongoDB view over `vessel_positions`.** Same execution cost as computing on
demand; a non-materialized view is not a cache.

**Last-write-wins during ingestion.** Simplest to implement and **incorrect**
for this dataset, per the out-of-order finding above. This is precisely the bug
the conditional update prevents, and it is covered by an explicit integration
test (out-of-order events must not regress state).

**Scheduled recomputation after import.** Would work for a batch-only system
but leaves `vessel_latest` wrong during ingestion and adds a second pipeline
stage to keep correct. The conditional upsert costs little and is always right.

## Consequences

**Accepted costs:**

- This is deliberate denormalization, and it is the one place SOUL.md §7
  sanctions it. The access pattern pays for it: 16,294 documents replace a
  5.9M-document aggregation on every map pan.
- Ingestion does one extra bulk `updateOne` per batch alongside the position
  inserts, so write amplification is real.
- The denormalized name/type can drift if `vessels` is corrected without
  refreshing `vessel_latest`. `navisight-data validate` checks for this, and
  a rebuild path exists.

**Benefits realised:**

- The map query becomes a bounded `2dsphere` lookup over a small collection.
- Out-of-order source data cannot corrupt current state, and the guarantee is
  enforced by the database's match condition rather than by application
  sequencing.
- The upsert is idempotent: re-running an import cannot move state backwards.
