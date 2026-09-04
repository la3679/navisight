# Contributing to NaviSight

Read [`SOUL.md`](SOUL.md) first. It is the engineering constitution for this
repository and it outranks convenience. This document covers mechanics.

## Prerequisites

| Tool | Version used in development |
|------|-----------------------------|
| Python | 3.13 (`requires-python >= 3.12`) |
| [uv](https://docs.astral.sh/uv/) | 0.12+ — manages the Python toolchain and virtualenv |
| Node.js | 22 LTS |
| pnpm | 9+ |
| MongoDB | 8.0 — native install or `docker compose up -d mongodb` |

## Setup

```bash
cp .env.example .env          # PowerShell: Copy-Item .env.example .env
docker compose up -d mongodb  # skip if you already run mongod on 27017
```

Then follow [`docs/operations/LOCAL_DEVELOPMENT.md`](docs/operations/LOCAL_DEVELOPMENT.md),
which is the authoritative setup guide and works on PowerShell as well as
bash — Windows is a first-class development environment here, not an
afterthought.

## Branching

- **Never commit directly to `main`.**
- Branch names: `feat/…`, `fix/…`, `docs/…`, `perf/…`, `test/…`, `chore/…`.
- Never force-push a shared branch or rewrite published history.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/). Scope by
subsystem where it helps: `data`, `db`, `api`, `web`, `3d`, `ai`, `infra`,
`docs`.

```text
feat(api): expose vessel trajectory endpoint with bounded point count
fix(data): reject positions outside the physical coordinate range
perf(db): add compound index for per-vessel history queries
```

Before every commit:

1. `git status` and read what changed.
2. Run the formatter, linter, and type checker for the code you touched.
3. Run the relevant tests.
4. Read the staged diff — `git diff --cached`.
5. Confirm no secret, no `.env`, no raw AIS data, and no build artifact is staged.

Do not use `git add .` without reading the diff. Prefer explicit paths.

## Quality gates

These run in CI and must pass locally before you push.

**Backend** (from `apps/api/`):

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy .
uv run pytest
```

**Frontend** (from `apps/web/`):

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

Integration tests need MongoDB running and use a **separate** database
(`MONGODB_TEST_DATABASE`), which is dropped between runs. Never point it at a
database holding data you care about.

CI never downloads the AIS dataset. Every automated test runs against small
deterministic synthetic fixtures.

## Things that will get a change rejected

Drawn directly from [`SOUL.md`](SOUL.md) §17:

- A performance number that was estimated rather than measured.
- Mock data hardcoded into the UI so a screenshot looks populated.
- Calling the historical dataset "live" or "real-time" anywhere user-visible.
- An index added without naming the query it serves.
- Giving the LLM the ability to author a query, run code, or exceed its bounds.
- Loading the full CSV into memory.
- Committing the dataset, or a "small" subset of it.
- Weakening a type or a guardrail to make a check pass.
- A new dependency without a stated reason the platform cannot do the job.
- Failing tests in a change marked complete.

## Optional: code-graph navigation

[Graphify](https://pypi.org/project/graphify-ai/) can index this repository into
a queryable symbol graph, which is useful for finding call paths and impact
radii without grepping. It is a **developer aid only** — nothing in the API, the
web application, or CI imports it, and no build step depends on it.

```bash
graphify extract . --code-only --no-cluster   # local AST only, no API key
graphify cluster-only . --no-label            # communities, no LLM naming
graphify god-nodes --top 10                   # most connected symbols
graphify affected "parse_row()"               # what a change would touch
```

`--code-only` and `--no-label` keep the whole thing offline. The semantic modes
call an LLM; they are optional and were not used to produce anything committed
here.

Everything Graphify writes lands in `graphify-out/`, which is git-ignored.
Do not commit it: it is a derived artifact that goes stale the moment the code
moves.

## Architecture decisions

Non-obvious or hard-to-reverse decisions get an ADR in [`docs/adr/`](docs/adr/),
using the existing files as the template: Context, Decision, Alternatives
considered, Consequences. Write down the alternatives you actually rejected and
the costs you actually accepted — an ADR that lists no downside is not finished.
