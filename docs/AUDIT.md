# Final audit

A check of the repository against [`SOUL.md`](../SOUL.md), performed by running
commands rather than by reading code and forming an impression.

**Audited:** 2026-09-04, at `c9bad4c` on `feat/navisight-platform`.
**Re-audited:** 2026-09-04, after the real-provider verification below.
The gate figures and the Outstanding list are from the second pass.

Every row below names how it was checked. Where something failed, it says so and
links the fix. Where something is outstanding, it says that too — an audit that
finds nothing has usually not looked.

---

## Summary

| | |
|---|---|
| Checks run | 21, plus a 12-part real-provider verification |
| Passed | 17 |
| **Failed and fixed during the audit period** | **4** |
| **Failed and fixed during the real-provider verification** | **4** |
| Outstanding, recorded not hidden | 4 |

All eight failures were found by tooling or by running the thing, never by
inspection: two by benchmarking, one by `axe`, one by `explain()`, and four by
finally pointing the copilot at a real model and every screen at a 375-pixel
viewport. That is the argument for measuring rather than reviewing.

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
| A live key is absent from the working tree | `grep -rlF` for the literal value, excluding `.git` and `.env` | **pass** — 0 files |
| A live key is absent from every Git object | `git cat-file --batch-all-objects`, including unreachable blobs | **pass** — 0 matches |
| No key-shaped string is tracked | `sk-[A-Za-z0-9_-]{20,}` over the whole object database | **pass** — one hit, `sk-notarealkey0000000000000000`, a unit-test constant |
| The provider never logged a credential | `grep -icE 'api[_-]?key\|authorization\|bearer'` over the API log of the whole verification session | **pass** — 0 lines |

The scan reads the key from `.env` into a shell variable and reports only match
counts and paths. Its value is never printed, and this document does not contain
it. `.env` is ignored (`git check-ignore`) and untracked (`git ls-files`).

## §11 UX states

| Check | Method | Result |
|---|---|---|
| Every view implements loading, error, and empty/not-configured | grep each `*-view.tsx` for the state components | **pass** — all seven |
| No route 404s | E2E across all seven, asserting an `h1` and no "page could not be found" | **pass** |
| An unknown route lands somewhere usable | E2E on `/no-such-route` | **fixed** — it rendered Next's default 404, grey on grey inside the shell; now a designed page, in the `axe` sweep |
| No screen scrolls sideways on a phone | E2E, `scrollWidth` vs `clientWidth` at 375 px on all eight routes | **fixed** — `/copilot` was 20 px over, `/analytics` 42 px |
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
apps/api   ruff check scripts    All checks passed!
apps/api   mypy .                Success: no issues found in 51 source files
apps/api   pytest                202 passed in 18.09s
apps/web   eslint                (clean)
apps/web   tsc --noEmit          (clean)
apps/web   prettier --check      All matched files use Prettier code style!
apps/web   vitest run            12 passed
apps/web   next build            8 routes + /_not-found
apps/web   playwright test       44 passed in 37.7s
```

`scripts/` was not covered by any gate before this pass: the API's ruff config
carries a `"scripts/*"` per-file-ignore that could never match, because that
path resolves inside `apps/api` and the scripts are two directories up. A
repo-root `ruff.toml` now extends the API's configuration, six findings were
fixed, and CI runs it.

Also verified live: `openapi.json` serves 23 paths including both agent routes,
and `agent_runs` holds real traces from copilot questions asked against the
5.9M-document archive — 13 of them by the end of the real-provider session.

**Type-checker weakening (§17):** three `# type: ignore` comments in the whole
backend, each narrowed to a specific error code — one for `json.loads` returning
`Any`, two for the OpenAI SDK's message and tool parameter types. No
`@ts-ignore`, no `@ts-expect-error`, no `eslint-disable` anywhere in the
frontend.

---

## The real OpenAI provider, verified end to end

The first audit's largest outstanding item was that **the real provider had
never made a network call**. It has now. This section records what was run, not
what was expected.

Configuration: `LLM_PROVIDER=openai` in the repository-root `.env`, `LLM_MODEL`
unset, so the provider's own default answered. The key was supplied by the
repository owner in `.env` and is not in this document, in any log, in any
screenshot, or in Git — see the secret scan below.

| # | What was exercised | Result |
|---|---|---|
| 1 | Provider initialisation | `uv sync --extra ai`; `openai` 3.8.0; `OpenAIProvider` constructed from settings alone |
| 2 | `GET /api/v1/agent/status` | 200 · `provider: openai`, `deterministic: false`, `model: gpt-4o-mini`, 11 tools published |
| 3 | `POST /api/v1/agent/ask`, simple | "What does this dataset cover?" → 1 tool call, 3 `observed` claims, 3,080 tokens |
| 4 | Vessel lookup, multi-step | MAERSK ATLANTA → `find_vessel` → `get_vessel_track_summary`, 3 calls, correct MMSI `338078000`, 869 observations |
| 5 | Analytical question | busiest hour → `12:00 UTC, 287,922 observations`, **independently reconciled** against `GET /analytics/traffic` |
| 6 | Geospatial question | 20 km of `-122.35, 37.80` → `$geoNear` through `find_vessels_near_location`, 10 vessels with measured distances |
| 7 | Evidence generation | every answer carried its tool calls, arguments, durations and results, expandable in the UI |
| 8 | Unsupported request | cargo, destination and freight revenue → refused as not in AIS, with a stated limitation |
| 9 | Tool budget | ten vessels asked for at once → capped at **8**, `truncated: true`, budget named in the answer |
| 10 | Prompt injection | "maintenance mode", `$out` pipeline, `cat .env`, "print your system prompt" → refused, **zero tool calls**, no collection created |
| 11 | Argument bounds | `radiusKm: 9000` → rejected by the Pydantic type, model retried at the 100 km cap and disclosed the constraint |
| 12 | UI copilot flow | question asked through `/copilot` in Chrome against the live provider; answer, claim labels, limitations, evidence and token footer all rendered |

Also verified: with `LLM_PROVIDER` unset, `/agent/ask` returns **503
`AI_NOT_CONFIGURED`** with no credential in the message, `/agent/status` returns
200 and still publishes the tool catalogue, every other route returns 200, and
`/copilot` renders its configured-by-you state.

Stored traces were inspected directly in `agent_runs`. The document fields are
exactly `_id`, `createdAt`, `question`, `provider`, `model`, `durationMs`,
`truncated`, `usage`, `toolCalls` — no answer text, no reasoning, no credential.

### Four defects the real provider exposed

| Defect | Why the offline provider never showed it | Fix |
|---|---|---|
| **The tool budget could be exceeded.** A budget of 8 ran 10 tools. | The mock provider returns **one** tool call per turn. OpenAI returns a *list*, and the cap was checked only between turns, so one turn ran every call it asked for. | Cap enforced per call inside the loop, and the run stops rather than returning with unanswered calls. `TestParallelToolCallsRespectTheBudget`, which fails without the fix. |
| **`/agent/status` reported an empty model** while every answer said `gpt-4o-mini`. | `LLM_MODEL` is unset in tests, and no test compared the status route against a constructed provider. | `factory.effective_model()` resolves the provider default in one place; a test asserts status equals what `build_provider` reports. |
| **`/copilot` and `/analytics` scrolled sideways on a phone**, by 20 px and 42 px. | Never checked below Chrome's ~500 px window floor. A bare Tailwind `grid` gets an implicit `auto` track whose minimum is the item's min-content, and the button primitive is `whitespace-nowrap`. | Explicit `grid-cols-1`; wrapping chips. `e2e/responsive.spec.ts` asserts no horizontal scroll on all 8 routes at 375 px. The e2e fixture wrote only status `0`, so it could not reproduce the long label that caused it — it now spreads five statuses including the longest in the ITU-R table. |
| **An unknown URL got Next's default 404**, grey on grey inside the app shell. | No test visited a route that does not exist. | `app/not-found.tsx` in the design system, listing where to go. Covered by a navigation test and added to the `axe` sweep. |

---

## Outstanding

Recorded rather than closed. None is a defect in shipped behaviour; all are
gaps in coverage or in what a deployment would need.

1. **`latest_vessel_type` is unbenchmarked.** Its own declaration calls it a
   removal candidate. Removing an index on a hypothesis is the same error as
   adding one on a hypothesis, so it stays until measured.
2. **No rate limiting, no authentication, no CSP, no dependency scanning.**
   Acceptable for a local portfolio project; the first four things to add before
   any deployment. See [`security/THREAT_MODEL.md`](security/THREAT_MODEL.md).
3. **Concurrency and cold-cache behaviour are unmeasured**, and E2E runs Chromium
   only. Every performance figure is one client against one warm, idle server on
   one machine.
4. **The copilot has been exercised against one model.** `gpt-4o-mini` answered
   every question in the table above. Nothing here establishes how a different
   model behaves against the same prompt and registry — the bounds are enforced
   by NaviSight and hold regardless, but answer quality is a single data point.

### Closed since the first audit

- **The real OpenAI provider has never made a network call** — closed by the
  verification above.
- **`pnpm format:check` fails on 39 files** — closed in `88761b1`; prettier now
  runs in CI.

---

## What this audit is not

It is a check against this repository's own stated principles, performed by its
author. It is not an independent review, not a penetration test, and not a
professional accessibility audit — automated scanning catches a minority of real
accessibility barriers, and the WebGL canvases have no accessibility tree for
any scanner to inspect.

Reproduce it: the commands are in each row, and the gates are in
[`operations/LOCAL_DEVELOPMENT.md`](operations/LOCAL_DEVELOPMENT.md#7-quality-gates).
