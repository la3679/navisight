# ADR-0011: Precompute whole-archive analytics instead of indexing for them

- **Status:** Accepted
- **Date:** 2026-09-04

## Context

The analytics screen asks three questions of `vessel_positions` over the entire
imported window: observations and distinct vessels per time bucket, the speed
histogram, and the busiest vessels. Measured through the API against the real
5,928,519-document import, they took **43.6 s, 38.4 s and 31.8 s**.

`explain()` showed the traffic pipeline already using `position_timestamp` and
then fetching all 5.9M matched documents, because `mmsi` is not in that index. A
covering index on `(timestamp, mmsi, navigation.speedOverGroundKnots)` removed
the fetches entirely — `docsExamined` 0 — and reached **20.1 s**.

That is the important measurement, because it shows the ceiling. The query is
not selective: the requested window *is* the dataset, so every plan must visit
every record. Indexing changes the constant, not the shape.

Full figures and commands: [`../performance/ANALYTICS_QUERIES.md`](../performance/ANALYTICS_QUERIES.md).

## Decision

Compute the four answers once, after import, and store them in a small
`analytics_rollup` collection. `navisight-data rollup` builds them in about 2.6
minutes; the API serves them in ~0.22 s.

SOUL.md §13 says caching is added *after* a measurement shows it is needed. The
measurement above is that evidence, and the underlying fact that makes it safe
is that **the archive is immutable after import** — a whole-window aggregate
cannot change between two page loads.

Two conditions gate every rollup read, so a stale answer is not reachable:

1. the request window must **contain** the archive's full extent, otherwise the
   live pipeline runs;
2. `estimated_document_count()` must match the count recorded at build time,
   otherwise the rollup is ignored.

Responses carry `computedAt` when precomputed and omit it when aggregated live,
so which path answered is visible in the payload rather than inferred from how
fast it felt.

The covering index was **rejected**: 155.9 MiB and 60.8 s of build time for 2.2×
on a path that is now precomputed, on a collection already carrying 688 MiB of
indexes. `position_timestamp` stays, because a sub-day window still falls
through to the live pipeline and measures 1.95 s there.

## Alternatives considered

**Add the covering index and ship 20-second analytics.** Rejected on the number.
Twenty seconds is not a page load, and the index would be paid for on every
future import.

**Sample the collection and extrapolate.** Rejected outright. SOUL.md §3
forbids presenting an estimate as a measurement, and these figures are shown to
the user as counts. The rollup stores exact counts precisely so this trade never
has to be made.

**A generic response cache (Redis, or in-process TTL).** Rejected. It would make
the *second* request fast and leave the first at 43 s, it adds infrastructure
SOUL.md §5 forbids without a demonstrated need, and a TTL is the wrong
invalidation model for data that changes exactly once, at import. Recomputing on
a timer would be worse than recomputing never.

**Compute the rollup inside the import pipeline.** Not adopted *yet*. It is
attractive — one command instead of two — but the import is already the longest
operation in the system and coupling a 2.6-minute aggregation to it makes a
resumable job harder to reason about. A separate idempotent command that can be
re-run after a partial import is the smaller thing to get right. Revisit if
users forget to run it.

**Materialise on read (compute-and-store on first request).** Rejected: it hides
a 43-second request inside whichever unlucky page load arrives first, and makes
two concurrent first-requests race.

## Consequences

**Accepted costs:**

- A second command after import. Forget it and analytics still works and still
  returns correct numbers — it just takes 40 seconds a panel, which is a bad
  first impression that the README and CONTRIBUTING have to prevent.
- Derived state now exists in the database, so `navisight-data reset` has to
  clear it. `AIS_COLLECTIONS` includes it for exactly that reason: a summary of
  data that no longer exists would be worse than no summary.
- Custom time windows — a future agent tool, for instance — do not benefit and
  fall back to the live pipeline. The API's range cap bounds how slow that can
  get.
- One more moving part in a system SOUL.md §5 asks to keep holdable in one head.

**Benefits realised:**

- The analytics page loads in well under a second instead of taking over two
  minutes for six panels.
- The numbers are exact and reconcile with the import: traffic totals
  5,928,519, matching the imported position count.
- No new index, no new service, no new dependency. The whole mechanism is four
  documents and a guard.
