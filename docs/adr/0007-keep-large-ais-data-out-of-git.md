# ADR-0007: Keep the raw AIS dataset out of Git

- **Status:** Accepted
- **Date:** 2026-09-03

## Context

Development uses a 604,984,395-byte (0.56 GiB) daily AIS CSV. It is public data
published by NOAA/MarineCadastre, not data NaviSight owns.

## Decision

The dataset lives **outside** the repository, referenced through the
`AIS_DATA_PATH` environment variable. `.gitignore` blocks `ais-*.csv` by name
so an accidental copy cannot be staged. Only **derived aggregate statistics**
(`docs/data/AIS_PROFILE.md`, `docs/data/ais_profile.json`) are committed.

## Alternatives considered

**Commit the file.** Git stores full history and does not delta-compress a file
like this well. Every clone would pay ~0.56 GiB forever, including after a
later deletion, because the blob stays in history.

**Git LFS.** Moves the cost rather than removing it, and pushes bandwidth and
storage quota onto anyone who forks the project. It also does not address the
redistribution question.

**Commit a sampled subset.** Explicitly rejected by SOUL.md §17. A "small"
real subset is still redistribution, still grows history, and invites the
subset to drift from the real schema. Tests use **synthetic** fixtures in
`data/samples/` instead, which are hand-checkable and carry no provenance
question.

## Consequences

**Accepted costs:**

- The project cannot be run end-to-end against real data from a bare clone.
  `data/README.md` documents the download in four steps to reduce that friction.
- CI can never exercise the real dataset. This is arguably a benefit: it forces
  the automated tests to depend on deterministic fixtures instead.

**Benefits realised:**

- Clone size stays small.
- No redistribution of data NaviSight does not own.
- The published profile statistics remain verifiable — anyone can download the
  same source file and re-run `navisight-data profile` to check every number.
