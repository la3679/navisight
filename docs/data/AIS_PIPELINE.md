# The ingestion pipeline

How 5,929,631 CSV rows become 5,928,519 position documents, 16,294 vessel
records, and a materialized current-state collection — streaming, resumably,
and idempotently.

All figures here are from the real run recorded in `ingestion_runs`.

---

## The measured run

```
rowsRead              5,929,631
rowsValid             5,929,631
rowsRejected                  0
positionsInserted     5,928,519
positionsDuplicate        1,112
vesselsUpserted          16,294
latestUpdated           265,783
batches                   1,209
durationSeconds       1,055.995      (17 min 36 s)
rowsPerSecond           5,615.2
sourceBytes         604,984,395      (0.56 GiB)
sourceChecksum   f679e50b77a6491b39a2418618b457ae
```

`5,929,631 − 1,112 = 5,928,519`. The duplicates are not losses; see
[§3](#3-idempotent).

---

## The four constraints

From SOUL.md §6. Each one rules out an implementation that would otherwise be
simpler.

### 1. Streaming

The 0.56 GiB source is **never loaded whole**. Rows are parsed one at a time and
written in bounded batches of 5,000. Peak memory is a batch plus the vessel
accumulator, not a fraction of the file.

This rules out the obvious `pandas.read_csv()` opening, and it is why the
importer works the same on a laptop as on a large machine.

### 2. Resumable

A checkpoint row is written every 250,000 rows, along with the source
**checksum**. `--resume` matches on the checksum, not the filename, so a resumed
run cannot continue into a different file that happens to share a name.

The subtle part: **a crash between an insert and its checkpoint write is safe** —
but only because the insert is idempotent. The replayed rows collide on `_id`
and no-op. Resumability and idempotency are not two features here; the second is
what makes the first correct.

Ctrl+C is handled rather than fatal: the current batch finishes, a checkpoint is
written, and the run is marked `cancelled`.

### 3. Idempotent

Each position document's `_id` is a **deterministic fingerprint** — 12 bytes of
BLAKE2b over `mmsi | timestamp | longitude | latitude | transceiver`
([ADR-0006](../adr/0006-deterministic-event-fingerprint-for-idempotency.md)).

Re-running the import inserts nothing new. Every row computes the `_id` it had
before, and a duplicate-key error on that `_id` is counted rather than raised.

This is also what collapsed the **1,112 duplicates**: two rows agreeing on all
five components describe the same broadcast, so storing one is correct rather
than lossy. They are *reported*, not silently dropped — `positionsDuplicate` is
in the run record and on the `/data` screen.

BLAKE2b rather than Python's `hash()` because string hashing is randomized per
process, and idempotency across runs requires a value stable across processes.

### 4. Observable

**Rejections are counted by reason and never silently dropped.** `rejectReasons`
is a map in the run record; on this file it is empty, because
`rowsRejected` was 0.

A pipeline that quietly discards malformed rows leaves the operator believing
they have a complete archive. That is the failure this constraint exists to
prevent, and it is why the count is surfaced in the UI rather than only logged.

---

## The part that is easy to get wrong

**The source file is not chronologically ordered.** Measured: the first 50,000
rows already span 00:00 to 18:58 UTC.

So "last write wins" is wrong for `vessel_latest`. A naive update would leave
whichever observation happened to appear last in the file, not the newest one.

The guard has to be on the timestamp — and the obvious spelling of that is a
trap:

```python
# WRONG.
updateOne({"_id": mmsi, "timestamp": {"$lt": new}}, {"$set": ...}, upsert=True)
```

When a newer document already exists, the filter matches **nothing**, so the
upsert attempts an *insert* — which fails with a duplicate key on `_id`. Not
occasionally: on **every** stale row. With 5.9M observations collapsing into
265,783 accepted updates, the majority of rows are stale, so this fails almost
everywhere.

`build_latest_update()` uses an aggregation-pipeline `$replaceWith` instead,
which evaluates the comparison against the existing document and keeps it
unchanged when it is already newer. One statement, no error path, correct
regardless of file order.

---

## Vessel metadata: latest non-empty wins

Identity is folded into an in-memory `VesselAccumulator` per MMSI during the
import, then written once at the end
([ADR-0005](../adr/0005-accumulate-vessel-metadata-in-memory-during-ingestion.md)).

Holding this in memory is safe because the bound is the **vessel** count —
16,294 — not the row count.

Two rules, both from measurement:

- **A blank never overwrites a value.** Some broadcasts carry empty metadata
  fields. `is_empty` metadata is skipped entirely rather than merged.
- **An older broadcast never overwrites a newer one.** 371 vessels changed
  metadata during the profiled day, and the file is not ordered, so each field
  is only accepted from a broadcast at least as new as the one that set it.
  `metadataUpdatedAt` records when.

NaviSight does **not** adjudicate which of two conflicting broadcasts was
correct. It takes the newest non-empty value and records the time it was taken.

The `$min`/`$max` on `firstSeenAt`/`lastSeenAt` make the write order-independent
and safe to re-apply, so a resumed run cannot narrow a window it previously
widened.

---

## Throughput, and why it decays

**5,615 rows/s overall.** But throughput is not flat: measured over the first
200k rows it falls from **28.8k to 9.6k rows/s**.

The important measurement is that it decays *even with the optional position
indexes disabled*. The decay is therefore dominated by the **mandatory `_id`
index** — 251.2 MiB, the largest index on the collection — not by the optional
ones. Disabling indexes to speed up an import buys less than it appears to.

**Create indexes before importing, not after.** `navisight-data import` does
this by default. Building a 2dsphere index over 5.9M *existing* documents is a
long blocking operation; building it incrementally during the load is not.

---

## After the import

```bash
uv run navisight-data rollup     # REQUIRED
uv run navisight-data validate
uv run navisight-data status
```

`rollup` is not optional in practice. Whole-archive analytics measured **31–44
seconds per panel** live and **~0.22 s** from the rollup
([ADR-0011](../adr/0011-precompute-whole-archive-analytics.md)). Skipping it is
*safe* — the numbers are identical — it is just slow enough to look broken.

`validate` runs six consistency checks; all six passed on this import.

---

## Order of operations

```
profile   →  measure the source before trusting it
indexes   →  create them BEFORE the load
import    →  stream, batch, checkpoint, collapse duplicates
rollup    →  precompute whole-archive analytics
validate  →  six consistency checks
status    →  what is loaded, and what is not configured
```

---

## See also

- [`AIS_SOURCE_REFERENCE.md`](AIS_SOURCE_REFERENCE.md) — the source schema and
  its documented valid domains.
- [`AIS_PROFILE.md`](AIS_PROFILE.md) — measured completeness of the source file.
- [`../database/DATA_MODEL.md`](../database/DATA_MODEL.md) — what the documents
  look like once written.
- [`../database/INDEXING.md`](../database/INDEXING.md)
- ADRs [0005](../adr/0005-accumulate-vessel-metadata-in-memory-during-ingestion.md),
  [0006](../adr/0006-deterministic-event-fingerprint-for-idempotency.md),
  [0007](../adr/0007-keep-large-ais-data-out-of-git.md),
  [0009](../adr/0009-treat-source-timestamps-as-utc.md).
