# Local development

The authoritative setup guide. Every command has been run on Windows
(PowerShell) and works on bash — **Windows is a first-class development
environment here**, not an afterthought, and where the two differ both are
given.

Read [`SOUL.md`](../../SOUL.md) first if you have not.

---

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.13 (`requires-python >= 3.12`) | installed by `uv`, not by you |
| [uv](https://docs.astral.sh/uv/) | 0.12+ | manages the toolchain and virtualenv |
| Node.js | 22 LTS | |
| pnpm | 9.15.9 | pinned via `packageManager` |
| MongoDB | 8.0 | native, or `docker compose up -d mongodb` |

---

## 1. Configuration

```bash
cp .env.example .env
```

```powershell
Copy-Item .env.example .env
```

One `.env` at the **repository root** serves both applications. It is
git-ignored; `.env.example` is committed with every value blank or safe.

Nothing needs editing to get started. The defaults point at
`mongodb://localhost:27017` and leave the AI copilot unconfigured, which is a
supported state rather than a broken one.

---

## 2. MongoDB

```bash
docker compose up -d mongodb
```

Skip it if you already run `mongod` on 27017. Check either way:

```bash
docker compose ps
```

```powershell
Test-NetConnection localhost -Port 27017
```

---

## 3. Backend

```bash
cd apps/api
uv sync --all-groups          # add --extra ai for the OpenAI provider
uv run uvicorn app.main:app --reload
```

`http://localhost:8000/docs` serves the generated OpenAPI document.

`uv sync` creates `.venv` and installs the pinned Python itself — there is no
`python -m venv` step and no need for a system Python of the right version.

---

## 4. Frontend

```bash
cd apps/web
pnpm install
pnpm dev
```

`http://localhost:3000`.

**Do not run `next dev` directly.** The `dev` and `build` scripts are chained as
`node scripts/sync-map-worker.mjs && next dev`, and that first step is not
optional: it stages MapLibre's Web Worker into `public/maplibre/`. Without it
**every map on every page renders blank, silently** — no error, no exception,
just a canvas that never draws. The full diagnosis is
[ADR-0010](../adr/0010-serve-the-maplibre-worker-from-our-own-origin.md), and it
cost two sessions to find.

The chaining uses `&&` rather than a `pre` script deliberately: pnpm does not
run `pre`/`post` hooks by default.

---

## 5. Data

The raw AIS CSV is **not in the repository** — ~600 MB, and
[ADR-0007](../adr/0007-keep-large-ais-data-out-of-git.md) explains why. See
[`data/README.md`](../../data/README.md) for how to obtain it.

Without it, everything still runs: the API starts, the web app loads, and each
screen reports "no data imported" rather than failing.

With it:

```bash
cd apps/api
uv run navisight-data profile          # measure the source before trusting it
uv run navisight-data indexes          # create indexes BEFORE importing
uv run navisight-data import           # ~18 min for 5.9M rows
uv run navisight-data rollup           # REQUIRED — see below
uv run navisight-data validate
uv run navisight-data status
```

### Run `rollup` after every import

Not optional in practice. Whole-archive analytics measured **31–44 seconds per
panel** live and **~0.22 s** from the rollup — a 193x difference on a screen
with six panels. Skipping it is *safe*; the numbers are identical either way.
It is just slow enough to look broken.
[ADR-0011](../adr/0011-precompute-whole-archive-analytics.md).

### Indexes before import, not after

`navisight-data import` does this by default. Building a 2dsphere index over 5.9M
*existing* documents is a long blocking operation; building it incrementally
during import is not.

### Never modify the source CSV

Do not copy it into the repository, edit it, or re-import over a good archive
without reason. Import is idempotent
([ADR-0006](../adr/0006-deterministic-event-fingerprint-for-idempotency.md)), so
re-running is safe — it just costs 18 minutes.

---

## 6. The AI copilot (optional)

Unconfigured by default, and that is a first-class state: `/copilot` renders
setup instructions plus the full tool catalogue, and every other screen is
unaffected.

**Offline, no key, no spend** — this is how the feature is developed and tested:

```
LLM_PROVIDER=mock
```

**A real model:**

```
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=<your key>
```

plus `uv sync --extra ai`.

The key is read **only** by the backend, from `.env` at the repository root. It
is never logged, never returned in a response, and cannot reach the browser —
`NEXT_PUBLIC_*` is a frontend build-time namespace and this variable is never
read there. Never put a credential in a `NEXT_PUBLIC_*` variable, and never
commit `.env`. See [`../ai/AI_SAFETY.md`](../ai/AI_SAFETY.md).

---

## 7. Quality gates

All of these run in CI and must pass locally before you push.

**Backend** — from `apps/api/`:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy .
uv run pytest
```

Integration tests need MongoDB and use a **separate** database
(`MONGODB_TEST_DATABASE`, dropped between runs). Without a server reachable they
skip rather than fail, so `pytest` works on a machine with no MongoDB — you just
get less coverage. No test ever touches the real archive.

**Frontend** — from `apps/web/`:

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

**End to end** — from `apps/web/`:

```bash
pnpm e2e:install     # once: downloads Chromium
pnpm e2e
```

Playwright starts both servers itself. Seed a synthetic archive first if your
database is empty:

```bash
cd apps/api
uv run python ../../scripts/data/seed_e2e_dataset.py
```

That generates ~5,760 invented observations across 20 vessels. It is
**not** the real dataset and is labelled `SYNTHETIC (e2e fixture)` so it cannot
be mistaken for one.

---

## 8. Benchmarks

```bash
cd apps/api
uv run python ../../scripts/benchmarks/query_benchmarks.py --json out.json
```

Read-only. Results in
[`../performance/BENCHMARKS.md`](../performance/BENCHMARKS.md) — **do not quote
those numbers as yours**; they are one machine's.

---

## 9. Windows notes

Things that cost real time here, recorded so they cost you none.

**Killing a stuck server.** `pkill -f uvicorn` does **not** work. A stale API
process once served old code for twenty minutes while a fix was being debugged.
Use:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

Check `StartTime` on the listening PID before trusting a measurement — it tells
you which build is actually answering.

**`python` from inside `apps/api`.** A pyenv shim intercepts it, so a heredoc
like `python - <<'PY'` fails there while working from the repository root. Use
`uv run python` inside `apps/api`.

**Line endings.** `.gitattributes` normalises to LF in the repository. The CRLF
warnings on commit are expected and correct.

---

## 10. Verifying visual work

**Verify maps and 3D in a real browser.** In-process headless panes commonly
freeze `requestAnimationFrame` — `document.hidden` stays `true` and rAF never
fires — and MapLibre's style load and react-three-fiber's render loop both await
it. Both then appear permanently blank for reasons that have nothing to do with
the code. Two independent things failing identically is a signal to suspect the
environment, not the code.

The E2E suite handles this correctly and is the reliable check:

```bash
cd apps/web && pnpm e2e
```

---

## 11. Optional: Graphify

A local code-graph tool used as a navigation aid. Not required, and its output
is git-ignored.

```bash
graphify extract . --code-only --no-cluster
graphify cluster-only . --no-label
```

Measured on this repository: **1,114 nodes, 2,489 edges, 82 files, 105
communities**. No API key needed in this mode.

`graphify claude install` is deliberately **not** run: it writes a hook into
your Claude Code settings, which is your decision rather than the repository's.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Maps blank, no error | `public/maplibre/` not staged. Run `pnpm sync:map-worker`. [ADR-0010](../adr/0010-serve-the-maplibre-worker-from-our-own-origin.md) |
| Analytics take ~40 s a panel | Rollup not built. `uv run navisight-data rollup`. |
| `/ports` shows "not configured" | Correct. No gazetteer ships; load one or leave it. |
| `/copilot` shows "not configured" | Correct. Set `LLM_PROVIDER`. |
| API changes not taking effect | A stale process on :8000. See §9. |
| Integration tests all skip | No MongoDB reachable. Expected, not a failure. |
| `pnpm build` fails at prerender | A client hook such as `useSearchParams()` needs a Suspense boundary. `next dev` does not surface this. |
