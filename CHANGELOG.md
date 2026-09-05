# Changelog

All notable changes to NaviSight, in the format of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioned per
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**About the dates and the tags.** NaviSight was built in three working sessions
across 3–4 September 2026. The milestone tags below were applied
**retrospectively on 2026-09-04**, each pointing at the commit that actually
brought that state into being. The dates in each heading are the **commit**
dates, which are real; no release was published on any of them, and this file
does not claim otherwise. `v1.0.0` is the first tag that coincides with its own
publication.

Every figure quoted here was measured by tooling in this repository.

---

## [1.0.0] — 2026-09-04

The first public release. Everything below was verified against the real
5.9M-document import and, for the copilot, against a live model.

### Added

- **Real-provider verification for the Maritime Intelligence Copilot.** Twelve
  scenarios through the full stack — browser, Next.js, FastAPI, the agent loop,
  the OpenAI provider, the allow-listed tools, MongoDB — covering provider
  initialisation, simple and multi-step questions, an analytical question
  reconciled independently against the REST API, a `$geoNear` geospatial
  question, evidence generation, unsupported requests, the tool budget, argument
  bounds, prompt injection, and the UI flow. Recorded in
  [`docs/AUDIT.md`](docs/AUDIT.md#the-real-openai-provider-verified-end-to-end).
- **A designed 404 page** (`app/not-found.tsx`) listing where to go, replacing
  Next's default, which rendered grey on grey inside the application shell.
- **`e2e/responsive.spec.ts`** — every route asserted to fit a 375 px viewport
  without horizontal scroll.
- **Documentation screenshots** captured from the running application against the
  real import by `apps/web/scripts/capture-screenshots.mjs`, which aborts if the
  API is serving the synthetic test fixture. Provenance in
  `docs/screenshots/manifest.json`.
- **[ADR-0013](docs/adr/0013-hand-written-agent-loop-instead-of-an-orchestration-framework.md)**
  — a hand-written agent loop instead of LangGraph, LangChain, or a vendor agent
  SDK, with the cost of that decision stated.
- **Lint and format gates for `scripts/`**, which no gate had ever covered: a
  repo-root `ruff.toml` extending the API's configuration, plus a CI step.
- `CHANGELOG.md`.

### Fixed

- **The agent tool budget could be exceeded.** A budget of 8 ran 10 tools. The
  offline test provider returns one tool call per turn; OpenAI returns a list,
  and the cap was checked only between turns. Now enforced per call, and the run
  stops rather than returning to a provider with unanswered calls.
- **`GET /api/v1/agent/status` reported an empty model** while every answer named
  `gpt-4o-mini`. `factory.effective_model()` resolves the provider default in one
  place; a test asserts the status route agrees with a constructed provider.
- **`/copilot` and `/analytics` scrolled sideways at 375 px**, by 20 px and 42 px.
  A bare Tailwind `grid` gets an implicit `auto` track whose minimum is the
  item's min-content, and the button primitive is `whitespace-nowrap`.
- **The end-to-end fixture wrote only navigational status `0`**, so it could not
  reproduce the longest label in the ITU-R M.1371 table — the string that caused
  the analytics overflow. It now spreads five statuses.
- **A stale `mypy` override** naming `langgraph`, `langchain_core` and `anthropic`
  — packages this project has never depended on.
- **A dangling bind mount.** `docker-compose.yml` mounted
  `infra/docker/mongo-init`, which did not exist.

### Changed

- `README.md` rewritten: a visual tour, MongoDB and geospatial design, the
  ingestion pipeline, the copilot's tool architecture and safety properties,
  measured performance, full setup including Windows, repository structure, and
  attribution.
- `docs/AUDIT.md` no longer states that the real OpenAI provider has never made a
  network call. It records what was tested instead.

---

## [0.9.0] — 2026-09-04 — Hardening, CI, end-to-end, documentation

### Added

- **CI**: four jobs, none advisory — a `gitleaks` secret scan over full history,
  the backend gates, the frontend gates, and the E2E suite. It never downloads
  the dataset and never needs an LLM key.
- **34 end-to-end tests** (Playwright, Chromium) covering navigation, map
  rendering, the copilot, and `axe` accessibility sweeps, plus the synthetic
  fixture seeder they run against.
- **A query benchmark harness** (`scripts/benchmarks/query_benchmarks.py`)
  measuring every declared index against a forced scan.
- **Six documents** the code already pointed at but which did not exist,
  the system architecture with rendered Mermaid diagrams, and
  [`docs/AUDIT.md`](docs/AUDIT.md) — 21 checks against `SOUL.md`.

### Fixed

- **An index whose stated justification was false.** `latest_location_2dsphere`
  claimed to serve the map viewport; `explain()` said `COLLSCAN`, 0 keys
  examined. `$geoWithin: {$box}` is a legacy-coordinate operator a 2dsphere index
  cannot answer. The index is justified by `$geoNear` instead, and the claim was
  corrected rather than the code.
- **A 4.6-second query behind every page.** `/dataset/status` computed coverage
  with `$group`/`$min`/`$max` over all 5,928,519 documents (**4,658 ms**). Two
  sorted single-document reads answer it from the existing index in **0.77 ms**,
  `totalKeysExamined: 1`. The header badge calls that route on every screen.
- **Four accessibility defects found by `axe`**: the map page had no `h1` at all;
  status badges set text on a 12% tint of their own hue and failed AA at 10–11 px
  (light `good` measured **2.83:1**); two invalid definition lists; and a slider
  whose `aria-label` sat on the wrong element, so `role="slider"` had no
  accessible name.
- Prettier had never been run; 39 files reformatted and `format:check` added to
  CI.

---

## [0.6.0] — 2026-09-04 — Maritime Intelligence Copilot

### Added

- **A tool registry of 11 typed functions**, a provider boundary, and a bounded
  agent loop. The model never authors a query: no argument model has a field
  that could hold a filter, a pipeline, a projection, a sort, a collection name,
  or a field path, and a test asserts that over the whole registry.
  [ADR-0012](docs/adr/0012-give-the-copilot-tools-not-a-query-language.md)
- **`GET /api/v1/agent/status`** and **`POST /api/v1/agent/ask`**, returning every
  tool call with its arguments, duration and result. Not-configured is a 200 on
  status and a 503 with a stable code on ask — never a crash.
- **A deterministic offline provider** requiring no key and no network, which is
  what makes the loop's guarantees assertable rather than merely plausible.
- **The `/copilot` screen**, built around the evidence rather than the prose:
  four claim kinds shown as words, an explicit limitations line, and every tool
  call expandable.
- **`docs/ai/AI_SAFETY.md`** — the threat treatment, including what is not
  mitigated.

---

## [0.5.0] — 2026-09-04 — 3D, analytics, and port intelligence

### Added

- **The analytics screen** on hand-built SVG charts, with a table view beside
  every chart and each chart stating its own basis.
- **Port intelligence**: an operator-supplied gazetteer loader and radius
  proximity search. NaviSight ships no port list, and `/ports` says so — the AIS
  source contains no port information, and inventing one would put fabricated
  place names beside real vessel positions.
- **The overview screen**, with a 3D maritime scene labelled *illustrative*, and
  a vessel inspector rendering a hull scaled to each vessel's own reported
  dimensions, labelled *representative*.

### Changed

- **Whole-archive analytics are precomputed, not indexed for.** Live aggregations
  took **43.6 s, 38.4 s and 31.8 s**. A covering index on
  `(timestamp, mmsi, sog)` was built and measured: it eliminated all 5.9M
  document fetches and still took **20.1 s**, because the requested window *is*
  the dataset. The index was rejected (155.9 MiB, 60.8 s to build) and the
  answers are computed once after import: **0.22 s**, a 193x improvement, from
  four documents.
  [ADR-0011](docs/adr/0011-precompute-whole-archive-analytics.md)

---

## [0.4.0] — 2026-09-04 — The operations map

### Added

- Frontend foundation: Next.js 16, React 19, TypeScript strict, Tailwind v4,
  TanStack Query, the application shell, vessel search and vessel detail.

### Fixed

- **Both maps rendered blank, and it was not deck.gl.** `maplibre-gl` derives its
  Web Worker URL from `import.meta.url`, which under Turbopack resolves to a
  chunk path that **404s**. `new Worker(url)` does not throw on a 404, so the
  only symptom was one MIME-type line in the console. MapLibre then waited
  forever and the viewport query it gated never ran. Fixed by staging the worker
  into our own `public/`, and guarded by a test asserting the file is served.
  [ADR-0010](docs/adr/0010-serve-the-maplibre-worker-from-our-own-origin.md)

---

## [0.3.0] — 2026-09-03 — REST API and geospatial queries

### Added

- A versioned REST API over the archive: vessel search and detail, positions and
  simplified tracks, map viewport queries, proximity search, analytics, dataset
  status and quality, and reference code tables. Every list endpoint is bounded
  server-side — result limits, geospatial radii, time ranges, and trajectory
  point counts.
- Structured logging with a request ID on every log line, and `/health` and
  `/ready` that distinguish "the process is up" from "the database answered".

---

## [0.2.0] — 2026-09-03 — AIS profiling and MongoDB ingestion

### Added

- **A streaming profiler** over the source file, publishing measured
  completeness rather than assumed schema. It found heading absent from **50.6%**
  of rows and IMO from **60.1%** — which is why "missing" renders as an em dash
  throughout and never as a zero.
- **The MongoDB model**: positions separated from vessel metadata
  ([ADR-0002](docs/adr/0002-separate-vessel-metadata-from-position-history.md)),
  a materialized `vessel_latest` for the map
  ([ADR-0003](docs/adr/0003-maintain-materialized-latest-vessel-state.md)), and
  every index declaring the query it serves.
- **Resumable idempotent ingestion.** A position's `_id` is a deterministic
  fingerprint of `(mmsi, timestamp, longitude, latitude)`, so re-running a partly
  completed import is safe without a transaction
  ([ADR-0006](docs/adr/0006-deterministic-event-fingerprint-for-idempotency.md)).
- The `navisight-data` CLI: `profile`, `import`, `rollup`, `validate`, `status`,
  `ports`.

**Measured on the real file:** 5,929,631 rows read, **5,928,519** positions
stored, 1,112 duplicates collapsed, **0 rejected**, 16,294 distinct vessels, at
**5,615.2 rows/s** over 1,055.995 s.

---

## [0.1.0] — 2026-09-03 — Foundation

### Added

- [`SOUL.md`](SOUL.md), the engineering constitution the rest of this history is
  audited against, and the data-provenance record.
- The Python project with its gates set strict from the first commit: `ruff`,
  `ruff format`, `mypy --strict`, `pytest`.
- AIS normalisation and the ITU-R M.1371 vessel-type and navigational-status
  code tables, as pure functions with no I/O.
- Repository hygiene: an ignore policy that keeps the ~577 MiB source file and
  every secret out of Git
  ([ADR-0007](docs/adr/0007-keep-large-ais-data-out-of-git.md)), and an MIT
  licence covering NaviSight's own source only.

---

[1.0.0]: https://github.com/la3679/navisight/releases/tag/v1.0.0
[0.9.0]: https://github.com/la3679/navisight/releases/tag/v0.9.0
[0.6.0]: https://github.com/la3679/navisight/releases/tag/v0.6.0
[0.5.0]: https://github.com/la3679/navisight/releases/tag/v0.5.0
[0.4.0]: https://github.com/la3679/navisight/releases/tag/v0.4.0
[0.3.0]: https://github.com/la3679/navisight/releases/tag/v0.3.0
[0.2.0]: https://github.com/la3679/navisight/releases/tag/v0.2.0
[0.1.0]: https://github.com/la3679/navisight/releases/tag/v0.1.0
