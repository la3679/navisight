# ADR-0009: Treat source timestamps as UTC and store UTC internally

- **Status:** Accepted
- **Date:** 2026-09-03

## Context

`base_date_time` arrives as `2025-01-08 00:00:00` — no offset, no zone
designator. Guessing wrong shifts every observation in the system by hours and
would silently corrupt every time-window query, every hourly aggregation, and
every replay frame.

## Decision

Treat source timestamps as **UTC**, on citation rather than assumption.

The NOAA/MarineCadastre AIS data dictionary defines `base_date_time` as
*"Full UTC date and time"* (transcribed in
[`docs/data/AIS_SOURCE_REFERENCE.md`](../data/AIS_SOURCE_REFERENCE.md)), and the
publisher states that all NMEA-record timestamps use UTC.

Consequences of the decision:

- `parse_timestamp` always returns a timezone-aware UTC `datetime`. A naive
  datetime never leaves `app/domain/ais.py`, and a unit test asserts it.
- Ruff's `DTZ` rules are enabled to catch naive-datetime construction anywhere
  in the codebase.
- MongoDB stores BSON dates, which are UTC milliseconds since epoch.
- The API emits ISO-8601 with an explicit `Z`/offset.
- The UI labels displayed times. Any local-timezone conversion is opt-in and
  labelled; the source event time is never silently rendered in the viewer's
  zone (SOUL.md §11).

## Alternatives considered

**Assume UTC without checking.** The common shortcut, and the reason this ADR
exists. It happens to be right here, which is exactly why it is a bad habit —
it would have been indistinguishable from being wrong.

**Store naive datetimes and treat them as UTC by convention.** Rejected: the
convention lives in someone's memory rather than in the type, and the first
`datetime.now()` comparison introduces a bug that tests may not catch.

**Convert to the viewer's local zone at ingest.** Rejected: destroys the source
value, is meaningless for a dataset spanning US coastal waters from Guam to
Maine, and makes stored data depend on who imported it.

## Consequences

- All internal time handling is unambiguous, and comparisons are safe.
- The UI must always state the zone, which is slightly more chrome but removes
  a whole class of user misreading.
- If a future dataset is *not* UTC, `parse_timestamp` is the single place that
  changes, and this ADR is the record of why that would be a schema change
  rather than a tweak.
