# Analytics query performance

Every number here was produced by a command in this repository against the real
imported dataset — 5,928,519 position documents, MongoDB 8.0.4 running natively
on the development machine. Nothing is estimated. Re-run the commands to get
your own figures; do not quote these as if they were yours.

## The problem

The analytics screen asks three questions of `vessel_positions` over the whole
imported window:

| Endpoint | What it aggregates |
|---|---|
| `/analytics/traffic` | observations and distinct MMSIs per time bucket |
| `/analytics/speed` | every observation placed in a speed band |
| `/analytics/active-vessels` | observation count per MMSI, top N |

Measured end-to-end through the API, cold:

```bash
curl -s -o /dev/null -w "%{time_total}\n" \
  "http://localhost:8000/api/v1/analytics/traffic?start=2025-01-08T00:00:00Z&end=2025-01-08T23:59:59Z&interval=hour"
```

| Endpoint | Time |
|---|---|
| `traffic` (hourly) | **43.6 s** |
| `traffic` (15-minute) | **43.9 s** |
| `speed` | **38.4 s** |
| `active-vessels` | **31.8 s** |

## Why an index does not fix it

`explain(executionStats)` on the traffic pipeline:

```
IXSCAN  position_timestamp
FETCH
GROUP
totalKeysExamined  5,928,519
totalDocsExamined  5,928,519
executionTimeMillis 45,583
```

The index is used. The cost is the `FETCH`: `$mmsi` is not in
`position_timestamp`, so every one of the 5.9M matched index keys is followed by
a document read.

A covering index was built and measured:

```
db.vessel_positions.createIndex(
  { timestamp: 1, mmsi: 1, "navigation.speedOverGroundKnots": 1 })
```

| | keysExamined | docsExamined | traffic (hourly) |
|---|---|---|---|
| `position_timestamp` | 5,928,519 | 5,928,519 | 43.6 s |
| covering index | 5,928,519 | **0** | **20.1 s** |

The fetches are gone and it is still 20 seconds, because the query is not
selective: **the requested window is the entire dataset**, so any plan must
visit every record. No index makes a non-selective scan small.

The covering index costs 155.9 MiB and 60.8 s to build, on top of the existing
688 MiB of indexes on this collection. **It was rejected**: 2.2× on a path that
is about to be precomputed anyway does not justify that.

## What was done instead

`navisight-data rollup` computes the four answers once and stores them in
`analytics_rollup` — four documents. The archive is immutable after import, so a
whole-window aggregate cannot change between requests.

| Endpoint | Live | From rollup | Change |
|---|---|---|---|
| `traffic` (hourly) | 42.5 s | **0.220 s** | 193× |
| `traffic` (15-minute) | 43.5 s | **0.211 s** | 206× |
| `speed` | 39.3 s | **0.219 s** | 179× |
| `active-vessels` | 31.8 s | **0.228 s** | 140× |

Build cost, from `navisight-data rollup`:

```
coverage           2025-01-08 00:00:00+00:00 -> 2025-01-08 23:59:59+00:00
source documents   5,928,519
traffic:hour            43.57 s
traffic:15min           43.86 s
speed                   38.70 s
active-vessels          31.94 s
```

Roughly 2.6 minutes, once per import.

### The answers are identical, not approximate

The rollup stores exact counts from the same pipelines, so it is not a sampled
or estimated result. Verified against the live path:

- `traffic` total = **5,928,519**, which reconciles exactly with the imported
  position count.
- `speed` total = **5,915,980** with every band count matching the live
  response — the shortfall from 5,928,519 is the observations with no reported
  speed, which the pipeline excludes explicitly.

`tests/integration/test_rollup.py` runs both paths over synthetic data and
asserts the payloads are equal field for field.

### It cannot serve a stale answer

Two conditions gate every read, both cheap:

1. the request window must **contain** the archive's full extent — a narrower
   request falls through to the live pipeline;
2. `estimated_document_count()` must equal the count recorded when the rollup
   was built — any change to the collection invalidates it.

Measured fall-through, a one-hour window on the same data: **1.95 s**. This is
where `position_timestamp` earns its place, and why it was not dropped.

Responses carry `computedAt` when they came from the rollup and omit it when
aggregated live, so which path answered is visible rather than inferred.

## Reproducing

```bash
cd apps/api
uv run navisight-data rollup          # build, printing per-kind timings
uv run pytest tests/integration/test_rollup.py
```

Dropping the `analytics_rollup` collection is safe: the API returns the same
numbers from the live pipelines, slowly.
