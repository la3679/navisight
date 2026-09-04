# ADR-0005: Accumulate vessel metadata in memory during ingestion

- **Status:** Accepted
- **Date:** 2026-09-03

## Context

Every one of 5.9M source rows carries vessel metadata. Writing each one to the
`vessels` collection as it is seen would mean ~5.9M update operations to
maintain 16,294 documents — roughly 364 redundant writes per vessel.

The decision hinges on cardinality, which profiling measured rather than
estimated:

- **16,294 distinct MMSIs.**
- Only **371 vessels** ever changed metadata during the day, across **8,210**
  total changes.

## Decision

During ingestion, hold a `dict[str, VesselAccumulator]` keyed by MMSI in
process memory, tracking the latest non-empty value per field plus
`firstSeenAt` / `lastSeenAt`. Flush to `vessels` with a bulk upsert
periodically and at completion.

## Sizing (why this is safe)

16,294 vessels × roughly 400 bytes of accumulated Python objects is on the order
of **7 MB**. The profiler already holds comparable per-vessel structures and the
full run peaked well within normal process memory on a machine with 47.6 GB.
Even a dataset 100× larger — 1.6M vessels, far beyond the global AIS fleet —
would be around 700 MB and still tractable.

The bound is the **vessel count**, not the row count, and vessel count is
bounded by the real world: roughly 500k AIS-equipped vessels exist globally.
This is why the approach scales with more *days* of data (positions grow,
vessels do not) which is the direction this dataset actually grows.

## Alternatives considered

**Upsert on every row.** ~5.9M redundant writes, dominating ingestion time for
no benefit. Rejected.

**Upsert only on observed change.** Requires holding the last-seen signature
per MMSI anyway — the same memory — while saving little, since only 8,210
changes occur. A strictly more complex version of the chosen design.

**Two-pass import** (metadata pass, then positions pass). Doubles I/O over a
0.56 GiB file to avoid ~7 MB of memory. Rejected.

**Spill to a temporary collection.** The right answer *if* vessel count were
unbounded. It is not, and adding it now would be complexity without a
requirement (SOUL.md §5).

## Consequences

**Accepted costs:**

- Ingestion memory scales with distinct vessels. Documented, measured, and
  reported by the CLI so a future dataset that breaks the assumption is visible
  rather than silent.
- A crash loses in-memory metadata not yet flushed. This is safe by
  construction: resume re-reads from the last checkpoint row and re-accumulates,
  and the `vessels` upsert is idempotent.

**Benefits realised:**

- Metadata writes drop from ~5.9M to a few bulk upserts.
- "Latest non-empty value per field" is straightforward to implement correctly
  in one place, rather than as a conditional update expression.

**Guardrail:** the ingestion pipeline logs the accumulator size. If a future
dataset pushes distinct vessels past a configured threshold, that surfaces as a
warning rather than as an out-of-memory failure at 90% completion.
