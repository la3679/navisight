# ADR-0002: Separate vessel metadata from position history

- **Status:** Accepted
- **Date:** 2026-09-03

## Context

Each AIS row carries both a position event (time, coordinates, speed, course,
heading, status) and vessel identity metadata (name, IMO, call sign, type,
dimensions, draft, cargo). A one-to-one CSV import would copy all of it onto
every one of 5.9M documents.

Profiling measured the actual cardinality and churn:

| Measurement | Value |
|---|---|
| Position observations | 5,929,631 |
| Distinct vessels (MMSI) | 16,294 |
| Observations per vessel | min 1, p50 325, p90 844, max 1,305 |
| Vessels whose metadata changed at all | **371** (2.3%) |
| Total metadata changes across the day | **8,210** |

So metadata is ~364× lower cardinality than positions and is almost entirely
static.

## Decision

Split into three collections:

- **`vessels`** — one document per MMSI holding identity and metadata.
- **`vessel_positions`** — one document per observation, holding only what
  varies per observation, plus `mmsi` as the reference.
- **`vessel_latest`** — materialized current state, see
  [ADR-0003](0003-maintain-materialized-latest-vessel-state.md).

Position documents do **not** carry vessel name, IMO, call sign, dimensions,
type, or cargo.

## Alternatives considered

**Embed positions inside the vessel document.** Rejected outright. An unbounded
array is forbidden by SOUL.md §7, and the numbers show why it is not merely
stylistic: at 1,305 observations for the busiest vessel in *one day*, a
multi-day dataset breaches the 16 MB document limit, and every position insert
would rewrite a growing document.

**One flat collection, CSV-shaped.** The naive import. Rejected because it
duplicates ~60 bytes of largely-static metadata across 5.9M documents for no
query benefit, and because updating a vessel's name would require touching
every historical document that vessel ever produced.

**Denormalize metadata onto positions anyway, for read speed.** This is the
serious version of the previous option: it would let a "vessels near here"
query avoid a lookup. Rejected because `vessel_latest` already serves that
access pattern with 16,294 documents instead of 5.9M — the denormalization is
paid for once per vessel rather than once per observation.

## Consequences

**Accepted costs:**

- Queries that need vessel names alongside historical positions require a
  `$lookup` or a second fetch. This is a real cost, paid deliberately: those
  queries are bounded (a single vessel's track, or a page of results), so the
  join is over tens or hundreds of documents, not millions.
- The pipeline is responsible for keeping `vessels` consistent with what
  positions reference. `navisight-data validate` checks this.

**Benefits realised:**

- ~364× less duplicated metadata.
- A metadata correction updates 1 document, not up to 1,305.
- `vessels` is small enough (16,294 documents) to search and scan cheaply.
- Because only 371 vessels ever change metadata, in-memory accumulation during
  ingestion is safe — see [ADR-0005](0005-accumulate-vessel-metadata-in-memory-during-ingestion.md).

## Note on metadata conflicts

371 vessels broadcast changing metadata during a single day, 8,210 changes in
total, with one vessel changing 432 times. Some of this is legitimate (draft
changes with loading); some is AIS data quality noise. The pipeline keeps the
**latest non-empty** value per field and records `metadataUpdatedAt`, rather
than trying to adjudicate which broadcast was correct. This is documented as a
known limitation rather than presented as authoritative vessel registry data.
