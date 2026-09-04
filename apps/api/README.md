# NaviSight API & Data Pipeline

FastAPI service and the AIS data tooling behind NaviSight.

This package owns **all** MongoDB access. The browser never connects to the
database (see [`../../SECURITY.md`](../../SECURITY.md)).

## Layout

| Path | Responsibility |
|------|----------------|
| `app/config.py` | Env-driven settings, validated with pydantic-settings |
| `app/domain/` | Pure logic: AIS parsing/normalization, geo math, code lookups. No I/O. |
| `app/db/` | Mongo client, collection handles, index definitions |
| `app/ingest/` | Streaming profiler and resumable ingestion pipeline |
| `app/api/v1/` | HTTP routes and response models |
| `app/services/` | Query/aggregation logic between routes and the database |
| `app/agent/` | LangGraph copilot: typed state, allow-listed tools |
| `app/cli.py` | `navisight-data` command line |

`domain/` holds no I/O on purpose — it is the part that is cheap to test
exhaustively, and the parsing rules there are the ones most likely to be
subtly wrong.

## Commands

```bash
uv sync                       # create/refresh the environment
uv run navisight-data --help  # data pipeline CLI
uv run uvicorn app.main:app --reload
```

Quality gates (all run in CI):

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy .
uv run pytest
```

`pytest -m "not integration"` skips tests that need a running MongoDB.
