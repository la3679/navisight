<div align="center">

# NaviSight

**Maritime Vessel & Port Intelligence Platform**

Explore vessel movement. Investigate traffic. Ask the data.

</div>

---

NaviSight ingests a day of real **historical** AIS vessel-position broadcasts —
**5,928,519** of them, from **16,294** vessels — into MongoDB, and makes that
movement record explorable three ways: on a map, through analytics, and through
a copilot that answers by calling allow-listed data tools and shows you the
evidence behind every claim.

It is a personal portfolio engineering project modelled on real maritime
intelligence systems. It has no production users and is not deployed on behalf
of any organisation.

**Every number in this document was measured by tooling in this repository.**
Where a figure appears, the command that produced it is named. Nothing is
estimated, and nothing is rounded up for effect.

---

## What it does

| Screen | What it answers |
|---|---|
| `/` | What this deployment holds, and what period it covers |
| `/operations` | Where vessels were, on a map, with replay across the day |
| `/vessels`, `/vessels/{mmsi}` | Who a vessel is, and where it went |
| `/analytics` | How traffic, speed, and fleet composition varied |
| `/ports` | Which vessels' last position was near a port — *if* you load a gazetteer |
| `/copilot` | A natural-language question, answered with its evidence |
| `/data` | What was imported, how complete it is, and what is not configured |

---

## What it is not

- **Not a navigation, collision-avoidance, or safety-critical system.**
- **Not real-time.** The dataset is a single historical day, filtered by the
  publisher to one-minute resolution. The interface says "historical" in the
  header of every page and "latest observation in the archive" wherever a
  position appears, because that is what the data is
  ([ADR-0008](docs/adr/0008-use-historical-replay-not-live-simulation.md)).
- **Not a port database.** No gazetteer ships. The AIS source contains no port
  information, and inventing one would put fabricated place names beside real
  vessel positions, so `/ports` reports "not configured" until you load a
  registry you trust.
- **Not an AI product.** The copilot is optional and off by default. Every other
  feature works without it.
- Not a claim of ownership over public AIS data.

---

## The engineering, in five findings

The interesting parts of this project are the places where a measurement
contradicted an assumption.

### 1. A blank map that was not a rendering bug

Both maps rendered blank, and the suspected cause was deck.gl. It was not.
`maplibre-gl` derives its Web Worker URL from `import.meta.url`, which under
Turbopack resolves to a chunk path that **404s**. `new Worker(url)` does *not*
throw on a 404, so the only symptom was one MIME-type line in the console —
which a previous session had dismissed as noise. MapLibre then waited forever:
no source loaded, `map.on("load")` never fired, and the viewport query it gated
never ran.

Fixed by staging the worker into our own `public/`, and guarded by an E2E test
that asserts the file is served and that the viewport query returned a non-zero
count. [ADR-0010](docs/adr/0010-serve-the-maplibre-worker-from-our-own-origin.md)

### 2. Indexing could not fix the analytics, so they were precomputed

Whole-archive analytics took **43.6 s, 38.4 s and 31.8 s**. A covering index on
`(timestamp, mmsi, sog)` was built and measured: it eliminated all 5.9M document
fetches (`docsExamined 0`) and still took **20.1 s**, because the requested
window *is* the dataset — no index makes a non-selective scan small.

So the index was **rejected** (155.9 MiB, 60.8 s to build) and the four answers
are computed once after import instead: **0.22 s**, a 193x improvement, from
four documents and a two-condition staleness guard. No new index, no cache
service, no new dependency. [ADR-0011](docs/adr/0011-precompute-whole-archive-analytics.md)

### 3. An index whose stated justification was false

SOUL.md requires every index to name the query it serves. Benchmarking checked
whether the names were *true*, and one was not: `latest_location_2dsphere`
claimed to serve the map viewport. `explain()` says `COLLSCAN`,
`totalKeysExamined 0` — `$geoWithin: {$box}` is a legacy-coordinate operator a
2dsphere index cannot answer.

The index is still justified, by a different query: `$geoNear`, which MongoDB
*refuses to plan* without a geo index. The claim was corrected rather than the
code, with the numbers and the condition for revisiting it recorded in place.
[`docs/performance/BENCHMARKS.md`](docs/performance/BENCHMARKS.md)

### 4. A 4.6-second query behind every page

`/dataset/status` reported the archive's coverage with `$group`/`$min`/`$max`,
which must visit every document: **4,658 ms** over 5.9M. Two sorted
single-document reads answer it from the existing index in **0.77 ms**
(`totalKeysExamined: 1`) with identical values. The header badge calls that
route on every page, so it was 4.6 s of latency behind every screen.

### 5. The copilot cannot author a query, by construction

The usual implementation is text-to-query: give the model the schema, execute
what it writes, filter the dangerous parts. Every such filter is a blocklist
over a query language with hundreds of operators.

Instead the model selects from **11 typed functions**. No argument model has a
field that could hold a filter, a pipeline, a projection, a sort, a collection
name, or a field path — so a query is not something it can express, rather than
something it is asked not to write. A test asserts that property over the whole
registry, so adding such a field fails the build.

Every answer ships with its evidence: each tool call, its arguments, and its
result, expandable in the UI. [ADR-0012](docs/adr/0012-give-the-copilot-tools-not-a-query-language.md),
[`docs/ai/AI_SAFETY.md`](docs/ai/AI_SAFETY.md)

---

## Measured

| | |
|---|---:|
| Source rows read | 5,929,631 |
| Position documents stored | **5,928,519** |
| Duplicate observations collapsed | 1,112 |
| Rows rejected | 0 |
| Distinct vessels | **16,294** |
| Import throughput | 5,615 rows/s (17.6 min) |
| Coverage | `2025-01-08T00:00:00Z` … `23:59:59Z` |
| Position data / on disk / indexes | 1,790 MiB / 445 MiB / 688 MiB |

| Query | Scan | Indexed | Factor |
|---|---:|---:|---:|
| One vessel's track | 8,263.79 ms | **3.01 ms** | 2,745x |
| One-hour analytics window | 4,033.32 ms | **124.37 ms** | 32x |
| Archive coverage bounds | 4,658.56 ms | **0.77 ms** | 6,050x |
| Whole-archive traffic | 43.6 s | **0.22 s** | 193x |

Reproduce: `scripts/benchmarks/query_benchmarks.py`,
[`docs/performance/`](docs/performance/). These are one machine's numbers —
re-run them rather than quoting them.

**Gates:** 194 backend tests, 12 frontend unit tests, 21 end-to-end tests;
`ruff`, `ruff format`, `mypy --strict` over 51 files; `eslint`, `tsc`, and a
production build of 8 routes. All run in CI, which never downloads the dataset
and never needs an LLM key.

---

## Stack

**Backend** — Python 3.13, FastAPI, PyMongo (async for the API, sync for the CLI
and benchmarks), Pydantic v2, MongoDB 8. `mypy --strict`, `ruff`, `pytest`.

**Frontend** — Next.js 16, React 19, TypeScript strict, Tailwind v4, TanStack
Query, MapLibre GL + deck.gl, react-three-fiber. Charts are hand-built SVG, not
a charting library — the mark spec and the mandatory table view were less code
drawn directly than themed through one.

**AI** — one dependency, the provider SDK. No agent framework: the loop is ~150
lines and its guarantees (termination, evidence, allow-listing) are the point; a
graph abstraction would hide them.

**Deliberately absent:** Redis, Kafka, Elasticsearch, any vector database, and
any orchestration framework. Nothing has demonstrated a need (SOUL.md §5), and
adding one to look experienced is the thing that rule forbids.

---

## Getting started

```bash
cp .env.example .env
docker compose up -d mongodb

cd apps/api && uv sync --all-groups && uv run uvicorn app.main:app --reload
cd apps/web && pnpm install && pnpm dev
```

`http://localhost:3000` — and `http://localhost:8000/docs` for the API.

**This works with no data.** Every screen reports "no data imported" rather than
failing. To load the archive, see [`data/README.md`](data/README.md) for how to
obtain the source file, then:

```bash
cd apps/api
uv run navisight-data profile   # measure the source before trusting it
uv run navisight-data import    # ~18 min
uv run navisight-data rollup    # REQUIRED, or analytics take 40 s a panel
uv run navisight-data validate
```

Full guide, including Windows specifics and a troubleshooting table:
[`docs/operations/LOCAL_DEVELOPMENT.md`](docs/operations/LOCAL_DEVELOPMENT.md).

### The copilot

Off by default. For an offline deterministic stub that needs no key and no
network — which is how the feature is developed and tested — set
`LLM_PROVIDER=mock`. For a real model, set `LLM_PROVIDER=openai` and
`OPENAI_API_KEY`, and run `uv sync --extra ai`. The key is read only by the
backend, is never logged or returned, and cannot reach the browser.

---

## Dataset

U.S. Coast Guard AIS broadcast points, distributed by NOAA / MarineCadastre.
Development uses the daily file for **2025-01-08**.

The raw CSV is **not committed** ([ADR-0007](docs/adr/0007-keep-large-ais-data-out-of-git.md)).
See [`data/README.md`](data/README.md) for provenance, and
[`docs/data/AIS_SOURCE_REFERENCE.md`](docs/data/AIS_SOURCE_REFERENCE.md) for the
field-level schema and documented valid domains.

Its **measured** completeness is in
[`docs/data/AIS_PROFILE.md`](docs/data/AIS_PROFILE.md): heading is absent from
50.6% of rows and IMO from 60.1%. That is why "missing" renders as an em dash
throughout and never as a zero.

---

## Engineering principles

Non-negotiables live in [`SOUL.md`](SOUL.md). The short version: model MongoDB
for access patterns, never state a number that was not measured, never present
historical data as live, never let a model author a database query, and never
commit the dataset.

---

## Documentation

| Area | Document |
|---|---|
| Engineering constitution | [`SOUL.md`](SOUL.md) |
| Decision records | [`docs/adr/`](docs/adr/) |
| Local development | [`docs/operations/LOCAL_DEVELOPMENT.md`](docs/operations/LOCAL_DEVELOPMENT.md) |
| Data model | [`docs/database/DATA_MODEL.md`](docs/database/DATA_MODEL.md) |
| Indexing | [`docs/database/INDEXING.md`](docs/database/INDEXING.md) |
| Query benchmarks | [`docs/performance/BENCHMARKS.md`](docs/performance/BENCHMARKS.md) |
| Analytics performance | [`docs/performance/ANALYTICS_QUERIES.md`](docs/performance/ANALYTICS_QUERIES.md) |
| AI safety | [`docs/ai/AI_SAFETY.md`](docs/ai/AI_SAFETY.md) |
| Threat model | [`docs/security/THREAT_MODEL.md`](docs/security/THREAT_MODEL.md) |
| AIS source schema | [`docs/data/AIS_SOURCE_REFERENCE.md`](docs/data/AIS_SOURCE_REFERENCE.md) |
| Measured data profile | [`docs/data/AIS_PROFILE.md`](docs/data/AIS_PROFILE.md) |
| Data provenance | [`data/README.md`](data/README.md) |
| Third-party assets | [`docs/THIRD_PARTY_ASSETS.md`](docs/THIRD_PARTY_ASSETS.md) |
| Security policy | [`SECURITY.md`](SECURITY.md) |
| Contributing | [`CONTRIBUTING.md`](CONTRIBUTING.md) |

---

## Known gaps

Listed so their absence is not read as a pass. The threat model
([`docs/security/THREAT_MODEL.md`](docs/security/THREAT_MODEL.md)) carries the
full list.

- **No rate limiting and no authentication.** Acceptable locally; not for a
  deployment.
- **No Content-Security-Policy header.**
- **Concurrency is unmeasured.** Every performance figure is a single client
  against an idle server.
- **No cross-browser testing.** E2E runs Chromium only.
- **`latest_vessel_type` is unbenchmarked** and its own declaration calls it a
  removal candidate.
- **The basemap is Natural Earth 110m** — continental outlines only, with no
  coastline detail at harbour zoom. `NEXT_PUBLIC_MAP_STYLE_URL` is wired and
  unset.

---

## License

[MIT](LICENSE), covering NaviSight's source code only. Source data and
third-party assets carry their own terms — see [`data/README.md`](data/README.md)
and [`docs/THIRD_PARTY_ASSETS.md`](docs/THIRD_PARTY_ASSETS.md).
