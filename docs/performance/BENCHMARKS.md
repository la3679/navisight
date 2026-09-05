# Query benchmarks

What each index is actually worth, measured against the real imported archive.

SOUL.md §7 requires every index to serve a *named* query, and says an index
nobody can name a query for gets deleted. `apps/api/app/db/indexes.py` names the
query for each one. This document checks whether the name is **true** — because
an index justified by a plausible sentence and no number is precisely what that
rule exists to catch.

It caught one. See [§4](#4-the-index-that-was-not-doing-its-stated-job).

---

## Conditions

| | |
|---|---|
| Data | **5,928,519** position documents, 16,294 vessels |
| MongoDB | 8.0, running natively on the development machine |
| Repeats | 5 per query (3 for collection scans), **median** reported |
| Script | [`scripts/benchmarks/query_benchmarks.py`](../../scripts/benchmarks/query_benchmarks.py) |
| Raw output | [`query_benchmarks.json`](query_benchmarks.json) |

These are one machine's numbers, and they are not yours. Re-run the script.

**Method.** Each query runs twice against the same collection, same process,
same warm cache: once as MongoDB plans it, once with `hint({"$natural": 1})` to
force a collection scan. Hinting rather than dropping the index is deliberate —
dropping and rebuilding takes minutes on 5.9M documents, changes the collection
between the two measurements, and can leave a database without an index if the
script dies halfway.

The median is reported rather than the minimum, which flatters, or the mean,
which one slow run distorts.

---

## 1. Results

| Query | Planned | Forced scan | Factor |
|---|---:|---:|---:|
| One vessel's track | **3.01 ms** | 8,263.79 ms | **2,745x** |
| One-hour window, all vessels | **124.37 ms** | 4,033.32 ms | **32x** |
| Map viewport (`$box`) | 55.06 ms | 42.64 ms | **1x** |
| Map viewport as GeoJSON polygon | **3.95 ms** | — | — |
| Distance-sorted proximity (`$geoNear`) | **3.02 ms** | *cannot run* | — |
| Same viewport over full history | 537.60 ms | — | — |
| Vessel name prefix search | 0.79 ms | 0.99 ms | **1x** |
| Archive coverage bounds | **0.77 ms** | 4,658.56 ms | **6,050x** |

`explain()` for each planned query — this is what separates "the index was used"
from "the index existed":

| Query | returned | keysExamined | docsExamined |
|---|---:|---:|---:|
| One vessel's track | 335 | 335 | 335 |
| One-hour window | 287,922 | 287,922 | 287,922 |
| Map viewport (`$box`) | 338 | **0** | **16,294** |
| Map viewport as polygon | 338 | 347 | 341 |
| Same viewport over full history | 5,000 | **0** | 135,426 |
| Vessel name prefix | 50 | 50 | 50 |
| Coverage bounds | 1 | 1 | 1 |

---

## 2. The indexes that clearly earn their place

**`position_mmsi_timestamp` — 2,745x.** One vessel's track goes from 8.26
seconds to 3 ms. `keysExamined` equals `docsExamined` equals `nReturned` (335),
so the compound `(mmsi asc, timestamp desc)` order satisfies both the equality
match and the sort: no blocking `SORT` stage, no over-fetch. This is the index
the product cannot function without — a vessel detail page would otherwise be an
8-second collection scan.

**`position_timestamp` — 32x, on the query it exists for.** A one-hour window
takes 124 ms indexed and 4.03 s scanned. Note that it examines all 287,922
matching documents either way; the win is not visiting the other 5.6 million.

This settles a question the code left open. The whole-archive analytics are
served from the precomputed rollup ([ADR-0011](../adr/0011-precompute-whole-archive-analytics.md)),
so it was fair to ask whether this index still had a job on a single-day
dataset. It does: any **sub-day** window falls through to the live pipeline, and
that is the path measured here.

**`vessel_name_normalized` — 1x, and kept anyway.** Prefix search is 0.79 ms
indexed against 0.99 ms scanned, which is not a difference. `vessels` holds
16,294 documents; a scan of that is already fast. The index is retained because
it costs nothing to maintain (one entry per vessel, written once at import) and
its cost model is the *fleet* size, which is what would grow. This is recorded
as an honest 1x rather than presented as a win.

---

## 3. The coverage-bounds fix

The largest factor here, on the most-called route in the product.

`GET /api/v1/dataset/status` reports the archive's first and last timestamps,
and the dataset badge in the header calls it on **every page** — so its latency
sat behind every screen. It used the obvious spelling:

```javascript
db.vessel_positions.aggregate([
  {$group: {_id: null, min: {$min: "$timestamp"}, max: {$max: "$timestamp"}}}
])
```

`$group` must visit every document to know the extremes, so it scanned all
5,928,519: **4,658.56 ms**.

Two sorted single-document reads answer the same question from the index, one in
each direction:

```python
first = await collection.find_one({}, {"timestamp": 1}, sort=[("timestamp", 1)])
last  = await collection.find_one({}, {"timestamp": 1}, sort=[("timestamp", -1)])
```

**0.77 ms**, `totalKeysExamined 1`, `totalDocsExamined 1`, identical values. No
new index — the one that already existed simply was not being used for this
question. End to end through the API, `/dataset/status` went from 4.6 s to
0.012 s.

Full write-up in
[`ANALYTICS_QUERIES.md`](ANALYTICS_QUERIES.md#dataset-status-the-coverage-bounds).

---

## 4. The index that was not doing its stated job

`latest_location_2dsphere` was documented as serving *"the operations map's
primary query: GET /api/v1/map/vessels for a viewport"*.

**It does not.** The map viewport measures 55.06 ms planned against 42.64 ms
scanned — the scan is, if anything, marginally quicker — and `explain()` is
unambiguous:

```
stage: COLLSCAN
totalKeysExamined: 0
totalDocsExamined: 16294
```

The cause is that `BoundingBox.to_geo_query()` filters with
`$geoWithin: {$box: ...}`. `$box` is a **legacy-coordinate operator**: a
`2dsphere` index cannot answer it. It was chosen for a real reason — the
viewport is a screen rectangle in degrees, and `$box` treats it as exactly that,
whereas a GeoJSON polygon has geodesic edges that bow away from the constant
latitude line a screen actually shows.

The same rectangle expressed as GeoJSON *does* use the index — 347 keys, 341
documents, **3.95 ms**, about 14x faster — and returned an **identical 338
documents** for this box.

### What was done about it

**The justification was corrected, and the query was left alone.** Three
reasons, in order:

1. **The index is still justified — by a different query.** `/api/v1/geo/nearby`
   and the agent's `find_vessels_near_location` run `$geoNear`, and MongoDB
   *refuses to plan `$geoNear` without a geo index at all*: hinting `$natural`
   returns `geoNear expression not allowed with $natural hint`. For those, the
   index is not an optimisation, it is the precondition. 3.02 ms.
2. **55 ms is acceptable, and its cost model is the right one.** `vessel_latest`
   is bounded by *vessel count*, not archive size — which is
   [ADR-0003](../adr/0003-maintain-materialized-latest-vessel-state.md)'s
   benefit and is entirely separate from this index. Asking the same viewport
   question of the full position history costs **537.60 ms** and examines
   135,426 documents, which is what the materialized collection avoids.
3. **The 338 = 338 agreement is not a guarantee.** Geodesic and planar edges
   diverge at wide boxes and high latitudes — this archive reaches ~61°N. A
   silent semantic change is worst exactly where it is hardest to notice.

So `indexes.py` and `geo.py` now say what is true, with these numbers, and name
the condition for revisiting: a fleet an order of magnitude larger.

This is what the "name the query" rule is for. The sentence was plausible, and
it was wrong for two sessions.

---

## 5. What is not measured here

Stated so nobody reads absence as a pass:

- **Concurrency.** Every figure is a single client against an idle server. There
  is no measurement of what happens under parallel load, and no connection-pool
  tuning has been done.
- **Cold cache.** Everything ran warm. First-request latency after a restart is
  unmeasured.
- **Write throughput.** Import throughput is a separate concern; these are read
  paths only.
- **Anything but this machine.** One developer laptop, native MongoDB, no
  replica set, no sharding, no network hop.
- **`latest_vessel_type`.** Its own declaration already calls it a removal
  candidate at 16k documents. It has not been benchmarked, so that remains an
  open question rather than a finding.

---

## Reproducing

```bash
cd apps/api
uv run python ../../scripts/benchmarks/query_benchmarks.py --json out.json
```

Read-only: the script creates nothing, drops nothing, and writes nothing to the
database.

## See also

- [`ANALYTICS_QUERIES.md`](ANALYTICS_QUERIES.md) — why whole-archive analytics
  are precomputed, including the covering index that was built, measured at
  20.1 s, and rejected.
- [ADR-0011](../adr/0011-precompute-whole-archive-analytics.md)
- [ADR-0003](../adr/0003-maintain-materialized-latest-vessel-state.md)
