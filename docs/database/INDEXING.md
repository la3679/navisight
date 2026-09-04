# Indexing

Every index in NaviSight, the query it serves, what it costs, and what it
measured.

SOUL.md §7: *every index exists to serve a named query; an index nobody can name
a query for gets deleted.* That is enforced structurally — `IndexSpec` cannot be
constructed without a `serves` string and a `write_cost` string, so an
undocumented index is not representable.

This document is the measured half. The declarations live in
`apps/api/app/db/indexes.py`; run `navisight-data indexes --explain` to print
them.

---

## Sizes, measured

`collStats` against the real 5,928,519-document import:

| Collection | Index | Size |
|---|---|---:|
| `vessel_positions` | `_id_` | 251.2 MiB |
| | `position_location_2dsphere` | 177.5 MiB |
| | `position_mmsi_timestamp` | 161.5 MiB |
| | `position_timestamp` | 98.3 MiB |
| | **total** | **688.5 MiB** |
| `vessel_latest` | `_id_` | 0.7 MiB |
| | `latest_location_2dsphere` | 0.8 MiB |
| | `latest_vessel_type` | 0.2 MiB |
| `vessels` | `_id_` | 0.2 MiB |
| | `vessel_name_normalized` | 0.2 MiB |
| | `vessel_call_sign` | 0.2 MiB |
| | `vessel_imo` | 0.1 MiB |

The indexes on `vessel_positions` total **688.5 MiB against 444.8 MiB of
compressed data** — more than the data they index. That asymmetry is the whole
reason the rule exists. There are three optional indexes on that collection, and
adding a fourth is a real decision, not a tweak.

---

## `vessel_positions` — 5.9M documents, every index expensive

### `position_mmsi_timestamp` — `(mmsi asc, timestamp desc)`

**Serves:** `GET /api/v1/vessels/{mmsi}/positions`, `/track`, and the vessel
detail timeline.

**Measured: 8,263.79 ms → 3.01 ms. 2,745x.**

`explain()`: `nReturned 335`, `totalKeysExamined 335`, `totalDocsExamined 335`.
Those three being equal is the point — the compound order means the `mmsi`
equality is satisfied first and the `timestamp` sort falls out of the index, so
there is no blocking `SORT` stage and nothing over-fetched.

The field order is load-bearing. `(timestamp, mmsi)` would satisfy neither: the
equality predicate would not be a prefix, and the sort would have to run in
memory.

This is the index the product cannot function without. Without it, opening one
vessel is an 8-second scan of 5.9M documents.

**Cost:** 161.5 MiB, one b-tree entry per position document, maintained
throughout import.

### `position_location_2dsphere` — `(location 2dsphere)`

**Serves:** historical spatial search — `GET /api/v1/geo/nearby` with a time
window, and the agent's `find_vessels_near_location` when scoped to history.

**Cost: 177.5 MiB, the most expensive index here.** 2dsphere keys are more
expensive to build than b-tree keys, across 5.9M documents.

Justified because spatial search over history is a core capability rather than a
nice-to-have. But note what the benchmark shows: asking a *viewport* question of
the full position history costs **537.60 ms** and examines 135,426 documents,
against 55.06 ms over `vessel_latest`. Live map queries must go to
`vessel_latest` ([ADR-0003](../adr/0003-maintain-materialized-latest-vessel-state.md));
this index is for the historical case.

### `position_timestamp` — `(timestamp desc)`

**Serves:** sub-day time-window analytics.

**Measured: 4,033.32 ms → 124.37 ms on a one-hour window. 32x.**

This one had an open question against it. Whole-archive analytics are served
from the precomputed rollup
([ADR-0011](../adr/0011-precompute-whole-archive-analytics.md)), and the dataset
is a single day — so did it still have a job? Yes: any **sub-day** window falls
through to the live pipeline, and that is the path measured. The API-level
figure for a one-hour window is **1.95 s**.

It also serves the archive coverage bounds, where it is worth **6,050x** —
4,658.56 ms as a `$group`/`$min`/`$max` scan, 0.77 ms as two sorted single
-document reads. See [`../performance/BENCHMARKS.md`](../performance/BENCHMARKS.md#3-the-coverage-bounds-fix).

**Cost:** 98.3 MiB.

### `_id_` — mandatory, and the largest

251.2 MiB, not optional, and doing real work beyond identity: the `_id` is the
observation fingerprint
([ADR-0006](../adr/0006-deterministic-event-fingerprint-for-idempotency.md)), so
this index is also what makes ingestion idempotent. A separate uniqueness index
would have been a second 251 MiB structure.

Storing the fingerprint as 12-byte BSON Binary rather than a 24-character hex
string halves that cost.

### The covering index that was rejected

`(timestamp, mmsi, navigation.speedOverGroundKnots)` was **built, measured, and
dropped**.

It worked as intended: `docsExamined 0`, no document fetches at all. It still
took **20.1 s** for whole-archive traffic, because the requested window *is* the
dataset — no index makes a non-selective scan small. For that it wanted 155.9
MiB and 60.8 s of build time on every import.

Building it and throwing it away was the right spend: the 20.1 s figure is what
justifies the rollup, rather than an assertion that indexing "wouldn't be
enough". [ADR-0011](../adr/0011-precompute-whole-archive-analytics.md).

---

## `vessel_latest` — 16,294 documents, cheap

### `latest_location_2dsphere` — and a correction

This was documented as serving the operations map's viewport query. **It does
not**, and the measurement is unambiguous:

```
map viewport ($geoWithin: {$box}) — COLLSCAN
totalKeysExamined: 0
totalDocsExamined: 16294
55.06 ms planned  /  42.64 ms forced scan
```

`$box` is a **legacy-coordinate operator**; a 2dsphere index cannot answer it.
`BoundingBox.to_geo_query()` uses `$box` on purpose — the viewport is a screen
rectangle in degrees and `$box` treats it as exactly that, whereas a GeoJSON
polygon has geodesic edges that bow away from the constant-latitude line a
screen shows.

The same rectangle as GeoJSON **does** use the index — 347 keys, 341 documents,
**3.95 ms**, ~14x — and returned an identical 338 documents.

**What the index actually serves:** `$geoNear`, in `GET /api/v1/geo/nearby` and
the agent's proximity tool. MongoDB *refuses to plan `$geoNear` without a geo
index* — hinting `$natural` returns `geoNear expression not allowed with
$natural hint`. There it is not an optimisation, it is the precondition.
**3.02 ms.**

The declaration in `indexes.py` now says this. The full reasoning for keeping
`$box` anyway — and the condition for revisiting — is in
[`../performance/BENCHMARKS.md`](../performance/BENCHMARKS.md#4-the-index-that-was-not-doing-its-stated-job).

### `latest_vessel_type` — an open question, not a finding

0.2 MiB. Declared as serving map and analytics filtering by vessel type.

**It has not been benchmarked.** Its own declaration already calls it a removal
candidate — a collection scan of 16k documents is fast — and the name-prefix
result below suggests it would measure at roughly 1x. That is a hypothesis, and
it is recorded as one. Measure it before removing it.

---

## `vessels` — 16,294 documents, search-oriented

### `vessel_name_normalized` — an honest 1x

**Measured: 0.99 ms scanned, 0.79 ms indexed.** That is not a difference.

Kept anyway, and the reason is cost model rather than current speed: 0.2 MiB,
one entry per vessel written once at import, and its size scales with *fleet*
size, which is the thing that would grow. Recorded as 1x rather than dressed up
as a win.

**It is prefix matching, and the code says so.** The uppercased `nameNormalized`
copy exists so an anchored regex `/^QUERY/` can use the b-tree without a
case-insensitive collation scan. An unanchored `/QUERY/` cannot use it at all
and degrades to a scan.

Substring and fuzzy matching would need a `text` index or Atlas Search. Neither
is present, because neither has been shown to be needed on 16k vessels — and
pretending a b-tree gives full-text semantics is exactly the kind of claim
SOUL.md §7 forbids.

### `vessel_imo`, `vessel_call_sign` — partial by construction

Both carry a `partialFilterExpression` restricting them to documents where the
field is a string. 60.1% of source rows carry no IMO, so a full index would be
mostly empty entries. 0.1 MiB and 0.2 MiB respectively.

Note a MongoDB constraint learned the hard way: `sparse` and
`partialFilterExpression` **cannot be combined** — the server rejects it at
runtime. `IndexSpec.__post_init__` raises on that combination, so it is a
definition error caught at import time rather than a failure during
`ensure_indexes`.

---

## Operational collections

| Index | Serves | Cost |
|---|---|---|
| `ingestion_source_started` | `--resume`: find the latest run for this exact checksum | negligible |
| `ingestion_status_started` | `/dataset/status`, `navisight-data status` | negligible |
| `agent_created` | recent copilot runs | negligible |
| `port_location_2dsphere` | port proximity; created only when a gazetteer is loaded | negligible |

---

## Practical notes

**Create indexes before a bulk import, not after.** `ensure_indexes()` is
idempotent, and building a 2dsphere index over 5.9M *existing* documents is a
long blocking operation. `navisight-data import` does this by default
(`--ensure-indexes`).

**Import throughput decays as the collection grows** — 28.8k → 9.6k rows/s over
200k rows — and it does so *even with the optional position indexes disabled*.
The decay is dominated by the mandatory `_id` index, not by the optional ones,
so disabling them buys less than it appears to.

**Before adding an index, write down the query.** Then measure it with
`scripts/benchmarks/query_benchmarks.py`, which compares the planned query
against the same query with `hint({"$natural": 1})`. If the factor is ~1x, say
so in the declaration — as `vessel_name_normalized` does — rather than implying a
win.

---

## See also

- [`DATA_MODEL.md`](DATA_MODEL.md)
- [`../performance/BENCHMARKS.md`](../performance/BENCHMARKS.md) — full method
  and results.
- [`../performance/ANALYTICS_QUERIES.md`](../performance/ANALYTICS_QUERIES.md) —
  why whole-archive analytics are precomputed instead of indexed for.
