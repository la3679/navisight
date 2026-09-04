# ADR-0006: Use a deterministic event fingerprint as `_id` for idempotency

- **Status:** Accepted
- **Date:** 2026-09-03

## Context

Ingesting 5.9M rows takes minutes and can be interrupted. Re-running it — after
a crash, a resume, or simply by accident — must not duplicate data. SOUL.md §6
requires ingestion to be both idempotent and resumable.

The obvious identity for an AIS observation is `(mmsi, timestamp)`. **This was
measured rather than assumed**, and the assumption is wrong.

Profiler results over the full file (`docs/data/AIS_PROFILE.md`):

| Measurement | Rows |
|---|---|
| Total rows | 5,929,631 |
| Rows repeating an already-seen `(mmsi, timestamp)` | **1,430** |
| …identical in position *and* transceiver (true duplicates) | **1,112** |
| …**different** position under the same `(mmsi, timestamp)` | **318** |

So `(mmsi, timestamp)` is not unique. Using it as a key would silently discard
318 genuine, distinct observations — vessels that broadcast more than once
within the same one-second stamp.

## Decision

Compute a **BLAKE2b-128 digest (12 bytes)** over the normalized tuple:

```text
mmsi | timestamp(ISO-8601, UTC) | longitude(.5f) | latitude(.5f) | transceiver
```

and use it as the `_id` of the `vessel_positions` document. Ingestion uses
unordered bulk inserts and treats duplicate-key errors as expected no-ops.

## Alternatives considered

**`(mmsi, timestamp)` compound `_id`.** Rejected on the measurement above — it
loses 318 real observations.

**Python's built-in `hash()`.** Rejected: string hashing is randomized per
process via `PYTHONHASHSEED`, so the same row would produce different ids in
different runs, destroying idempotency exactly when it matters (a resume in a
fresh process). There is a test that pins the digest and re-derives it in a
separate interpreter to prevent a future refactor from reintroducing this.

**MongoDB-generated `ObjectId` + a unique compound index.** Workable, but costs
a second 5.9M-entry index purely for deduplication, and pushes conflict
handling into index-violation handling anyway. Using `_id` gets the uniqueness
constraint for free from the index that must exist regardless.

**SHA-256.** No security property is needed here — this is a collision-
resistance-for-identity problem, not an adversarial one. BLAKE2b at 12 bytes is
faster and half the storage of a truncated SHA-256 hex string across 5.9M
documents.

**Digest length.** 12 bytes (96 bits) over ~5.9M items gives a birthday
collision probability on the order of 2×10⁻¹³ — negligible, while saving ~24
bytes per document versus a hex-encoded 128-bit id.

## Consequences

**Accepted costs:**

- `_id` is BSON Binary, not human-readable in `mongosh`. Accepted: it is an
  internal identity, and the API never exposes it.
- Two rows identical on all five components collapse into one. This is
  **correct** — they describe the same broadcast — but it means the stored
  document count is legitimately lower than the source row count.
- The fingerprint is coupled to the coordinate formatting (`%.5f`). That
  matches the documented 5-decimal source resolution, and changing it would
  change every id, so it is pinned by test.

**Verifiable prediction:**

> A full import of `ais-2025-01-08.csv` should insert
> **5,929,631 − 1,112 = 5,928,519** documents into `vessel_positions`.

This is the reconciliation target for `navisight-data validate`. An import that
lands on a different number indicates a bug, and the discrepancy must be
explained rather than accepted (SOUL.md §6).

**Benefits realised:**

- Re-running an import is safe by construction, with no pre-read.
- A crash between inserting a batch and writing the checkpoint cannot create
  duplicates on resume — the reinserted rows collide on `_id` and no-op.
