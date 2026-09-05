# ADR-0008: Present the data as historical replay, never as live tracking

- **Status:** Accepted
- **Date:** 2026-09-03

## Context

The dataset is a single historical day: profiling confirms coverage from
`2025-01-08T00:00:00Z` to `2025-01-08T23:59:59Z`, with 86,142 distinct
timestamps. It is also filtered by the publisher to one-minute resolution, so
even within that day it is a *sample*, not continuous telemetry — the busiest
vessel has 1,305 observations against a theoretical 1,440.

A maritime map showing moving vessels looks like live tracking. Presenting it
that way would be the single easiest and most dishonest way to make this
project look more impressive than it is.

## Decision

Every user-facing surface describes the data as historical.

**Permitted:** "historical AIS", "historical replay", "latest observation in
dataset", "last known position in the imported data".

**Prohibited in UI, docs, README, and commit messages:** "live tracking",
"real-time vessel feed", "currently at sea", "now underway".

The dataset date is displayed persistently in the application shell, not buried
in a tooltip. Replay controls are labelled with the UTC timestamp being
replayed.

No WebSocket or streaming transport is built, because there is nothing
streaming to carry. Adding one to make the UI *feel* live would be
infrastructure theatre for a false impression.

## Alternatives considered

**Replay in "real time" with a live-looking clock, disclosed in an About page.**
Rejected: the disclosure is not where the user looks, and the impression the
interface creates is the claim it makes.

**Interpolate between observations for smooth motion.** Not adopted. If it is
ever added, SOUL.md §4 requires interpolated positions to be visually and
structurally distinguishable from real observations, and the API to label them.
Sampled observations rendered honestly are preferable to smooth invented ones.

## Consequences

**Accepted costs:**

- The map is less visually seductive than a fake live feed would be.
- Vessel motion is stepped at the source's sampling interval rather than smooth.

**Benefits realised:**

- Every claim the interface makes is true.
- A future live-AIS integration can be added as a genuinely new capability
  rather than as a retraction.
