# Final audit

A check of the repository against [`SOUL.md`](../SOUL.md), performed by running
commands rather than by reading code and forming an impression.

**Audited:** 2026-09-04, at `c9bad4c` on `feat/navisight-platform`.

Every row below names how it was checked. Where something failed, it says so and
links the fix. Where something is outstanding, it says that too — an audit that
finds nothing has usually not looked.

---

## Summary

| | |
|---|---|
| Checks run | 21 |
| Passed | 17 |
| **Failed and fixed during the audit period** | **4** |
| Outstanding, recorded not hidden | 5 |

The four failures were all found by tooling, not by inspection: two by
benchmarking, one by `axe`, one by `explain()`. That is the argument for
measuring rather than reviewing.

---

## §3 Product truthfulness · §17 no estimated numbers

| Check | Method | Result |
|---|---|---|
| No hardcoded mock data in the UI | grep for `MOCK`/`FAKE`/`DUMMY`/`PLACEHOLDER` constants in `apps/web/src` | **pass** — none |
| Figures in README match the database | `navisight-data status`, `collStats`, `ais_profile.json` | **pass** — 5,928,519 / 16,294 / 1,112 / 0 rejected all reconcile |
| Completeness percentages are the profiler's | read `ais_profile.json` | **pass** — heading 50.595%, IMO 60.0992% |
| Performance figures were measured | every one traces to `scripts/benchmarks/query_benchmarks.py`, `ANALYTICS_QUERIES.md`, or `ingestion_runs` | **pass** |

Import throughput **5,615.2 rows/s** over **1,055.995 s** is read from the run
record, not from a stopwatch.

## §4 Historical-data honesty

| Check | Method | Result |
|---|---|---|
| No UI copy claims live or real-time data | grep `apps/web/src/**/*.tsx` for "real-time", "live feed", "currently at", "right now", excluding negations | **pass** — every occurrence is a denial |
| The dataset badge appears on every page | E2E test across `/`, `/operations`, `/analytics` | **pass** |
| `isHistorical` is structurally `true` | `Literal[True]` in `schemas.DatasetStatus` | **pass** — not representable otherwise |

## §7 MongoDB modelling

| Check | Method | Result |
|---|---|---|
| Every index names its query | iterate `INDEX_SPECS`, assert `serves` and `write_cost` non-empty | **pass** — 12 declared, none missing |
| Every named query is **true** | `query_benchmarks.py`, planned vs `hint($natural)` | **FAILED — fixed** |

> **Finding 1.** `latest_location_2dsphere` was documented as serving the map
> viewport. `explain()`: `COLLSCAN`, `totalKeysExamined 0`,
> `totalDocsExamined 16,294`; 55.06 ms planned against 42.64 ms forced-scanned.
> `$geoWithin: {$box}` is a legacy-coordinate operator a 2dsphere index cannot
> answer. The index *is* justified — by `$geoNear`, which MongoDB refuses to
> plan without a geo index — so the claim was corrected rather than the code.
> Fixed in `0076a82`; reasoning in
> [`performance/BENCHMARKS.md`](performance/BENCHMARKS.md#4-the-index-that-was-not-doing-its-stated-job).
>
> This is the check that justifies the rule. The sentence was plausible and it
> was wrong for two sessions.

## §8 AI behaviour · §9 evidence

| Check | Method | Result |
|---|---|---|
| No tool argument can carry a query | iterate `TOOLS`, intersect `model_fields` with a forbidden set (filter, pipeline, projection, sort, collection, field, expr, where, aggregate, code, path, url, eval, command) | **pass** — 11 tools, zero matches |
| Bounds are declared, not remembered | `MAX_ROWS=25`, `MAX_RADIUS_KM=100` on the field constraints | **pass** |
| Unknown tool names are refused before dispatch | `test_an_invented_tool_name_is_refused_and_nothing_dispatches` | **pass** |
| The loop terminates on its own budget | three tests incl. a provider that never stops asking | **pass** |
| Traces store tool calls and timings only | `test_the_trace_holds_tool_calls_and_timings_only` asserts the key set exactly | **pass** |
| Dataset text is inert | a fixture vessel named `IGNORE PRIOR ORDERS`, asserted at unit, integration and E2E levels | **pass** |
| Answers carry their evidence | E2E: an answer always renders an expandable tool call with its raw result | **pass** |
| The stub is never presented as a model | E2E asserts the notice is visible | **pass** |

The registry test is written over the **whole registry**, so adding a
query-shaped argument fails the suite rather than requiring someone to notice.

## §10 Security

| Check | Method | Result |
|---|---|---|
| `.env` is not tracked | `git ls-files` | **pass** |
| No AIS data committed | `git ls-files \| grep csv` | **pass** — nothing |
| No `$where`, `$function`, `$accumulator` | grep `apps/api/app` | **pass** — the only hit is a docstring saying it is not used |
| No `dangerouslySetInnerHTML` | grep `apps/web/src` | **pass** — none |
| CORS is an allow-list | read `main.py` | **pass** — explicit origins, enumerated methods and headers |
| The key never reaches a response | three tests, incl. asserting it is absent from every public attribute | **pass** |
| CI scans for secrets | `gitleaks` over full history | **pass** — added `e76b4ad`, because SECURITY.md claimed it before it was true |

## §11 UX states

| Check | Method | Result |
|---|---|---|
| Every view implements loading, error, and empty/not-configured | grep each `*-view.tsx` for the state components | **pass** — all seven |
| No route 404s | E2E across all seven, asserting an `h1` and no "page could not be found" | **pass** |
| Not-configured is a rendered state, not an error | `/ports` returns 409, `/copilot` renders setup plus the tool catalogue | **pass** |

## §12 Accessibility

| Check | Method | Result |
|---|---|---|
| No serious/critical WCAG 2.1 A/AA violations | `axe-core` across all seven routes | **FAILED — fixed** |
| Exactly one `h1` per route | E2E | **FAILED — fixed** |
| Skip link works | E2E: first Tab, then Enter | **pass** |
| Keyboard-only copilot use | E2E: focus, type, Enter; disclosures via Enter | **pass** |
| Identity never colour-alone | E2E: claim labels and map legend are words | **pass** |

> **Finding 2.** `/operations` had **no `h1` at all** — the map is full-bleed and
> the topmost heading was an `h2`, which gives a screen-reader user a broken
> outline. Fixed with a visually-hidden `h1`, and the suite now asserts one on
> every route.
>
> **Finding 3.** Two invalid `<dl>` structures: a definition list of `<div>`/`<p>`
> on the home page, and a `<p>` inside `<dl><div>` in the `Field` primitive used
> across `/data`.
>
> **Finding 4.** Every tinted badge failed contrast. The palette's status hues
> were validated against `--ns-surface`, but the badges set 10–11px text on a
> **12% tint of the same hue**, which lifts the background toward the text.
> Measured against their own tints: light-mode `good` at **2.83:1**, five more
> between 3.4 and 4.3. Fixed with `--ns-*-on-tint` tokens, each solved to the
> smallest shift reaching 4.5:1 so the design is visually unchanged.
>
> **Finding 5.** The replay slider had no accessible name: `aria-label` was on
> `Slider.Root`, but Radix puts `role="slider"` on the Thumb.
>
> All fixed in `9aceb92`.

## §13 Performance

| Check | Method | Result |
|---|---|---|
| Caching added only after measurement | ADR-0011 records 43.6 s live, a covering index built and measured at 20.1 s, then rejected | **pass** |
| No unbounded query is reachable | every bound declared once in `deps.py` | **pass** |
| Hot paths measured | `query_benchmarks.py`, 8 queries, median of 5 | **pass** |

> **Finding 6.** `/dataset/status` took **4.6 s** — on the route the header badge
> calls on *every page*. `$group`/`$min`/`$max` must visit all 5,928,519
> documents; two sorted `find_one`s answer it from the existing index in
> **0.77 ms** (`totalKeysExamined 1`), identical values. **0.012 s** end to end.
> Fixed in `6d26888`.

## §14 Documentation · §15 dependencies

| Check | Method | Result |
|---|---|---|
| No dangling doc references | resolve every `docs/**/*.md` path referenced from code, README, SECURITY, CONTRIBUTING | **pass** — six were missing at the start of the audit period, all written in `e76b4ad` |
| Mermaid diagrams parse | rendered all five through Mermaid 11 in a real browser | **pass** |
| No unused dependency | `recharts` was declared and never imported | **fixed** — removed in `9aceb92` |
| ADRs list their downsides | each has a "Consequences / accepted costs" section | **pass** |

## §18 Definition of done

Run at audit time:

```
apps/api   ruff check            All checks passed!
apps/api   ruff format --check   52 files already formatted
apps/api   mypy .                Success: no issues found in 51 source files
apps/api   pytest                194 passed in 16.89s
apps/web   eslint                (clean)
apps/web   tsc --noEmit          (clean)
apps/web   vitest run            12 passed
apps/web   next build            8 routes
apps/web   playwright test       34 passed in 34s
```

Also verified live: `openapi.json` serves 23 paths including both agent routes,
and `agent_runs` holds 7 real traces from copilot questions asked against the
5.9M-document archive.

**Type-checker weakening (§17):** three `# type: ignore` comments in the whole
backend, each narrowed to a specific error code — one for `json.loads` returning
`Any`, two for the OpenAI SDK's message and tool parameter types. No
`@ts-ignore`, no `@ts-expect-error`, no `eslint-disable` anywhere in the
frontend.

---

## Outstanding

Recorded rather than closed. None is a defect in shipped behaviour; all are
gaps in coverage or in what a deployment would need.

1. **The real OpenAI provider has never made a network call.** Everything was
   built and tested against the deterministic offline provider. The pure paths —
   redaction, argument decoding, message translation — have 22 unit tests, but
   the round trip is unexercised, and this document does not claim otherwise.
2. **`pnpm format:check` fails on 39 files.** Pre-existing; prettier has never
   been run in this repository. Formatting-only churn, deliberately not bundled
   with feature work.
3. **`latest_vessel_type` is unbenchmarked.** Its own declaration calls it a
   removal candidate. Removing an index on a hypothesis is the same error as
   adding one on a hypothesis, so it stays until measured.
4. **No rate limiting, no authentication, no CSP, no dependency scanning.**
   Acceptable for a local portfolio project; the first four things to add before
   any deployment. See [`security/THREAT_MODEL.md`](security/THREAT_MODEL.md).
5. **Concurrency and cold-cache behaviour are unmeasured**, and E2E runs Chromium
   only. Every performance figure is one client against one warm, idle server on
   one machine.

---

## What this audit is not

It is a check against this repository's own stated principles, performed by its
author. It is not an independent review, not a penetration test, and not a
professional accessibility audit — automated scanning catches a minority of real
accessibility barriers, and the WebGL canvases have no accessibility tree for
any scanner to inspect.

Reproduce it: the commands are in each row, and the gates are in
[`operations/LOCAL_DEVELOPMENT.md`](operations/LOCAL_DEVELOPMENT.md#7-quality-gates).
