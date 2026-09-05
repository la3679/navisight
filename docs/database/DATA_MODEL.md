# Data model

How NaviSight stores 5.9M AIS observations, and why it is shaped this way.

Every document below is a **real record from the imported archive**, printed
from the development database, not an illustration. Every size is measured with
`collStats`.

---

## The shape of the problem

One day of U.S. AIS broadcasts is:

| | |
|---|---:|
| Source rows | 5,929,631 |
| Position documents stored | **5,928,519** |
| Exact duplicate observations collapsed | 1,112 |
| Distinct vessels | **16,294** |
| Rows rejected | 0 |

Two things follow from that, and they drive the whole model:

1. **Positions outnumber vessels 364 to 1.** Anything copied onto every position
   document is paid for 5.9 million times.
2. **The archive is append-only and then immutable.** It is a recording. After
   import nothing changes, which is what makes derived state safe
   ([ADR-0011](../adr/0011-precompute-whole-archive-analytics.md)).

---

## Collections

| Collection | Documents | Data | Indexes | Purpose |
|---|---:|---:|---:|---|
| `vessel_positions` | 5,928,519 | 1,790.1 MiB | 688.5 MiB | Every observation |
| `vessel_latest` | 16,294 | 4.1 MiB | 1.7 MiB | Newest state per vessel |
| `vessels` | 16,294 | 4.1 MiB | 0.7 MiB | Identity and metadata |
| `ingestion_runs` | 1 | — | — | Import lifecycle |
| `analytics_rollup` | 4 | — | — | Precomputed aggregates |
| `agent_runs` | varies | — | — | Copilot traces |
| `ports` | 0 by default | — | — | Operator-supplied gazetteer |

Names are constants in `app/db/collections.py`, never string literals, so a
rename is one edit and a typo is an import error rather than a silently empty
query.

---

## 1. `vessel_positions` — the event log

```json
{
  "_id": "<BSON Binary, 12 bytes>",
  "mmsi": "367793030",
  "timestamp": "2025-01-08T00:00:00Z",
  "location": { "type": "Point", "coordinates": [-122.40506, 47.68588] },
  "source": {
    "dataset": "NOAA/USCG AIS",
    "file": "ais-2025-01-08.csv",
    "transceiver": "B"
  },
  "navigation": {
    "speedOverGroundKnots": 4.6,
    "courseOverGroundDegrees": 155.5
  }
}
```

Measured: **316 bytes** average, 1,790.1 MiB logical, 444.8 MiB on disk after
WiredTiger compression.

### What is deliberately absent

**No vessel name, type, or dimensions.** Those live in `vessels`, one copy per
vessel rather than 364 copies per vessel
([ADR-0002](../adr/0002-separate-vessel-metadata-from-position-history.md)).
That is the single largest storage decision in the model.

**No null padding.** `navigation` in the record above has two keys, not five —
heading and status were not broadcast, so they are simply not stored. Missing is
represented by absence, once, rather than by `null` in some places and `0` in
others. Half the source rows have no heading and 60.1% no IMO, so this is the
normal case rather than an edge case.

### `_id` is the observation's fingerprint

12 bytes of BLAKE2b over `mmsi | timestamp | longitude | latitude | transceiver`
([ADR-0006](../adr/0006-deterministic-event-fingerprint-for-idempotency.md)).

This is what makes ingestion **idempotent**: re-running the import inserts
nothing new, because every document computes the same `_id` it had before. It is
also what collapsed the 1,112 duplicates — two rows agreeing on all five
components describe the same broadcast.

Two consequences, one good and one a real cost:

- **Good:** no separate uniqueness index. The `_id` index is mandatory anyway,
  so idempotency is free. At 251.2 MiB it is nonetheless the *largest* index on
  the collection.
- **Cost:** the id is not human-readable in `mongosh`. Stored as BSON Binary
  rather than a 24-character hex string, it halves id storage across 5.9M
  documents; the readability is the price.

BLAKE2b rather than Python's `hash()` because string hashing is randomized per
process, and idempotency across runs depends on the value being stable.

### `location` is GeoJSON, longitude first

Always `[longitude, latitude]`. It is the order GeoJSON specifies, the order
MongoDB's geo operators expect, and the reverse of how people say it — so it is
fixed here and converted only at the API boundary.

---

## 2. `vessel_latest` — materialized current state

```json
{
  "_id": "367793030",
  "mmsi": "367793030",
  "timestamp": "2025-01-08T23:59:05Z",
  "location": { "type": "Point", "coordinates": [-122.40507, 47.68591] },
  "speedOverGroundKnots": 17.4,
  "courseOverGroundDegrees": 153.7,
  "name": "WN1622SL",
  "vesselType": 37,
  "transceiverClass": "B"
}
```

16,294 documents, 4.1 MiB. [ADR-0003](../adr/0003-maintain-materialized-latest-vessel-state.md).

The operations map asks "what is in this viewport?" on every pan. Answering that
from `vessel_positions` means a `$sort` + `$group` over 5.9M documents on every
interaction. Answering it here is a bounded lookup over 16k.

Measured: the viewport query costs **55.06 ms** against `vessel_latest`, and
**537.60 ms** against the full position history — examining 135,426 documents
instead of 338. See [`../performance/BENCHMARKS.md`](../performance/BENCHMARKS.md).

This collection **denormalizes on purpose**: `name` and `vesselType` are copied
here so a map tooltip needs no join. The duplication is bounded by vessel count,
which is what makes it acceptable — the same copy into `vessel_positions` would
not be.

### The update is a pipeline, and that is not incidental

`build_latest_update()` uses an aggregation-pipeline `$replaceWith` guarded on
the timestamp, not the obvious form:

```python
# WRONG — this is a trap.
updateOne({"_id": mmsi, "timestamp": {"$lt": new}}, ..., upsert=True)
```

When a newer document already exists the filter matches nothing, so the upsert
attempts an **insert** and fails with a duplicate key on *every* stale row. With
265,783 updates applied during import, that is not a rare edge.

---

## 3. `vessels` — identity

```json
{
  "_id": "367793030",
  "mmsi": "367793030",
  "name": "WN1622SL",
  "nameNormalized": "WN1622SL",
  "callSign": "WDJ5962",
  "vesselType": 37,
  "dimensions": { "lengthMeters": 10, "widthMeters": 3 },
  "firstSeenAt": "2025-01-08T00:00:00Z",
  "lastSeenAt": "2025-01-08T23:59:05Z",
  "metadataUpdatedAt": "2025-01-08T23:59:05Z"
}
```

`_id` is the MMSI: it is already unique, already a string, and already how every
lookup arrives. A generated ObjectId would add an index and an indirection for
nothing.

`nameNormalized` is an uppercased copy, so an anchored prefix regex `/^QUERY/`
can use a b-tree index without a case-insensitive collation scan. This is prefix
matching and the code says so — it does not pretend a b-tree gives full-text
semantics. See [`INDEXING.md`](INDEXING.md).

`dimensions` omits `draftMeters` here because this vessel never broadcast one.
Absent, not zero.

**Metadata accumulates as "latest non-empty wins."** 371 vessels changed
metadata during the profiled day, and some broadcasts carry blanks. A blank must
not erase a value already held, and NaviSight does not adjudicate which of two
conflicting broadcasts was correct — it takes the newest non-empty value and
records when it was taken. The accumulator is held in memory during import,
bounded by *vessel* count rather than row count
([ADR-0005](../adr/0005-accumulate-vessel-metadata-in-memory-during-ingestion.md)).

---

## 4. `ingestion_runs` — what actually happened

One document per import, holding the real numbers from the real run:

```json
{
  "sourceFile": "ais-2025-01-08.csv",
  "sourceBytes": 604984395,
  "sourceChecksum": "f679e50b77a6491b39a2418618b457ae",
  "status": "completed",
  "lastCheckpointRow": 5929631,
  "stats": {
    "rowsRead": 5929631,
    "rowsValid": 5929631,
    "rowsRejected": 0,
    "positionsInserted": 5928519,
    "positionsDuplicate": 1112,
    "vesselsUpserted": 16294,
    "latestUpdated": 265783,
    "batches": 1209,
    "durationSeconds": 1055.995,
    "rowsPerSecond": 5615.2
  }
}
```

The checksum is what `--resume` matches on, so a resumed run cannot continue
into a different file that happens to share a name. `lastCheckpointRow` is where
it would continue from.

This collection is why the UI can say what it is showing. `/dataset/status`
reads it, and the `/data` screen renders it.

---

## 5. `analytics_rollup` — derived, and disposable

Four documents, keyed `traffic:hour`, `traffic:15min`, `speed`,
`active-vessels`:

```json
{
  "_id": "traffic:hour",
  "coverageStart": "2025-01-08T00:00:00Z",
  "coverageEnd": "2025-01-08T23:59:59Z",
  "sourceDocumentCount": 5928519,
  "computedAt": "...",
  "computeSeconds": 43.57,
  "payload": { "buckets": [ ... 24 entries ... ] }
}
```

Whole-archive analytics took 31–44 seconds live and take ~0.22 s from here.
Full reasoning and the covering index that was built, measured at 20.1 s and
rejected: [ADR-0011](../adr/0011-precompute-whole-archive-analytics.md).

Two conditions gate every read, so a stale answer is unreachable: the requested
window must **contain** the archive's full extent, and
`estimated_document_count()` must still equal `sourceDocumentCount`. Safe to
drop — the API returns identical numbers from the live pipelines, slowly.

Rebuild with `navisight-data rollup`. **Run it after any import**, or analytics
falls back to 40-second aggregations.

---

## 6. `agent_runs` and `ports`

`agent_runs` stores one document per copilot question: tool calls and timings
only, never a transcript and never hidden reasoning — neither is collected. The
shape is asserted exactly in the test suite, so an edit that starts recording
more fails rather than passing quietly. See
[`../ai/AI_SAFETY.md`](../ai/AI_SAFETY.md).

`ports` is **empty by default and stays that way**. The AIS source contains no
port information, so a port list has to come from a registry the operator loads.
Inventing one would put fabricated place names beside real vessel positions.
Until one is loaded, `/api/v1/ports` returns 409 `PORT_DATA_NOT_CONFIGURED`
rather than an empty array — so a client can tell "not set up" from "no matches".

---

## Storage summary

| | Data | On disk | Indexes |
|---|---:|---:|---:|
| `vessel_positions` | 1,790.1 MiB | 444.8 MiB | 688.5 MiB |
| `vessel_latest` | 4.1 MiB | 3.8 MiB | 1.7 MiB |
| `vessels` | 4.1 MiB | 1.4 MiB | 0.7 MiB |

The indexes on `vessel_positions` cost **more than the compressed data they
index**, which is why there are only three and why each one has to name the
query it serves. `_id_` alone is 251.2 MiB and is not optional.

---

## See also

- [`INDEXING.md`](INDEXING.md) — every index, its query, and what it measured.
- [`../performance/BENCHMARKS.md`](../performance/BENCHMARKS.md)
- [`../data/AIS_SOURCE_REFERENCE.md`](../data/AIS_SOURCE_REFERENCE.md) — the
  source schema and its documented valid domains.
- [`../data/AIS_PROFILE.md`](../data/AIS_PROFILE.md) — measured completeness of
  the source file.
- ADRs [0001](../adr/0001-use-mongodb-for-geospatial-event-storage.md),
  [0002](../adr/0002-separate-vessel-metadata-from-position-history.md),
  [0003](../adr/0003-maintain-materialized-latest-vessel-state.md),
  [0005](../adr/0005-accumulate-vessel-metadata-in-memory-during-ingestion.md),
  [0006](../adr/0006-deterministic-event-fingerprint-for-idempotency.md).
