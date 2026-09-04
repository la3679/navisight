"""``navisight-data`` — the AIS data pipeline command line.

    uv run navisight-data --help

Every command exits non-zero on failure, prints progress without flooding the
terminal, and handles Ctrl+C as a clean cancellation rather than a traceback.
"""

from __future__ import annotations

import json
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Annotated

import typer

from app.config import REPO_ROOT, get_settings
from app.db import collections as db_collections
from app.db import indexes as db_indexes
from app.db.client import server_version, sync_database
from app.ingest.pipeline import (
    DEFAULT_BATCH_SIZE,
    IngestionStats,
    file_checksum,
    ingest,
)
from app.ingest.profiler import profile_csv, render_markdown
from app.ingest.runs import (
    RunStatus,
    find_resume_point,
    finish_run,
    latest_run,
    start_run,
    validate_import,
)
from app.services import rollup as rollup_service

app = typer.Typer(
    name="navisight-data",
    help="NaviSight AIS data pipeline: profile, import, validate, and inspect.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def main() -> None:
    """NaviSight AIS data pipeline.

    Declared so the CLI stays a command *group* even when only one subcommand
    is registered — otherwise Typer promotes a lone command to the root and
    `navisight-data profile` stops parsing.
    """


_cancelled = False


def _install_sigint_handler() -> None:
    """Turn Ctrl+C into a cooperative stop instead of a traceback."""

    def handler(signum: int, frame: FrameType | None) -> None:  # noqa: ARG001
        global _cancelled
        if _cancelled:
            typer.secho("\nForced exit.", fg=typer.colors.RED, err=True)
            raise SystemExit(130)
        _cancelled = True
        typer.secho(
            "\nCancellation requested — finishing the current batch. Ctrl+C again to force.",
            fg=typer.colors.YELLOW,
            err=True,
        )

    signal.signal(signal.SIGINT, handler)


def was_cancelled() -> bool:
    """Whether the user asked to stop."""
    return _cancelled


def _resolve_source(explicit: Path | None) -> Path:
    """Locate the AIS source file, preferring an explicit path over settings."""
    path = explicit if explicit is not None else get_settings().ais_data_path
    if not path.exists():
        typer.secho(f"AIS source file not found: {path}", fg=typer.colors.RED, err=True)
        typer.secho(
            "Set AIS_DATA_PATH in .env or pass --source. See data/README.md for how to "
            "obtain the dataset.",
            err=True,
        )
        raise typer.Exit(code=2)
    if not path.is_file():
        typer.secho(f"Not a file: {path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)
    return path


@app.command("profile")
def profile_command(
    source: Annotated[
        Path | None,
        typer.Option("--source", "-s", help="AIS CSV to profile. Defaults to AIS_DATA_PATH."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", "-n", min=1, help="Stop after N rows (smoke tests)."),
    ] = None,
    out_dir: Annotated[
        Path,
        typer.Option("--out-dir", help="Where to write the JSON and Markdown reports."),
    ] = REPO_ROOT / "docs" / "data",
    write: Annotated[
        bool,
        typer.Option("--write/--no-write", help="Write report files, or print a summary only."),
    ] = True,
) -> None:
    """Profile the raw AIS CSV in one streaming pass.

    Produces the measured statistics the data model is designed against:
    row counts, null rates, coordinate and time ranges, code distributions, and
    — most importantly — whether ``(mmsi, timestamp)`` uniquely identifies an
    observation.

    The source file is opened read-only and never modified.
    """
    _install_sigint_handler()
    path = _resolve_source(source)

    size_gib = path.stat().st_size / 1024**3
    typer.secho(f"Profiling {path.name} ({size_gib:.2f} GiB)", fg=typer.colors.CYAN, bold=True)
    if limit is not None:
        typer.echo(f"  limited to {limit:,} rows")
    typer.echo("")

    started = time.perf_counter()

    def report_progress(rows: int) -> None:
        # Single rewritten line on stderr, so piping stdout to a file stays clean.
        elapsed = time.perf_counter() - started
        rate = rows / elapsed if elapsed > 0 else 0.0
        sys.stderr.write(f"\r  {rows:>12,} rows  |  {rate:>9,.0f} rows/s")
        sys.stderr.flush()

    try:
        result = profile_csv(path, limit=limit, progress=report_progress)
    except (OSError, ValueError) as exc:
        sys.stderr.write("\n")
        typer.secho(f"Profiling failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    sys.stderr.write("\r" + " " * 48 + "\r")
    sys.stderr.flush()
    typer.secho(
        f"Read {result.rows_read:,} rows in {result.duration_seconds:.1f}s "
        f"({result.rows_per_second:,.0f} rows/s)",
        fg=typer.colors.GREEN,
    )
    typer.echo(f"  valid            {result.rows_valid:,}")
    typer.echo(f"  rejected         {result.rows_rejected:,}")
    typer.echo(f"  distinct vessels {result.unique_mmsi:,}")
    typer.echo(f"  time range       {result.timestamp_min} .. {result.timestamp_max}")
    typer.echo(
        f"  (mmsi,timestamp) unique: "
        f"{'yes' if result.duplicate_mmsi_timestamp_pairs == 0 else 'NO'}"
        f"  [{result.duplicate_mmsi_timestamp_pairs:,} repeats, "
        f"{result.exact_duplicate_rows:,} exact, "
        f"{result.conflicting_mmsi_timestamp_rows:,} conflicting]"
    )

    if not write:
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC)
    payload = result.to_dict()
    payload["generated_at"] = generated_at.isoformat()

    json_path = out_dir / "ais_profile.json"
    md_path = out_dir / "AIS_PROFILE.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
    md_path.write_text(render_markdown(result, generated_at=generated_at), encoding="utf-8")

    typer.echo("")
    typer.secho(f"Wrote {json_path.relative_to(REPO_ROOT)}", fg=typer.colors.GREEN)
    typer.secho(f"Wrote {md_path.relative_to(REPO_ROOT)}", fg=typer.colors.GREEN)


def _load_profile_expectations() -> tuple[int | None, int | None]:
    """Read expected row and duplicate counts from the committed profile report.

    Used to reconcile an import against what the profiler measured, so a run
    that silently lost data cannot be reported as successful (SOUL.md §6).
    """
    report = REPO_ROOT / "docs" / "data" / "ais_profile.json"
    if not report.exists():
        return None, None
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
        return (
            int(payload["rows"]["read"]),
            int(payload["uniqueness"]["exact_duplicate_rows"]),
        )
    except (OSError, ValueError, KeyError):
        return None, None


@app.command("indexes")
def indexes_command(
    database_name: Annotated[
        str | None, typer.Option("--database", help="Override MONGODB_DATABASE.")
    ] = None,
    explain: Annotated[
        bool, typer.Option("--explain", help="Print why each index exists, without creating.")
    ] = False,
) -> None:
    """Create the declared indexes, or explain what each one is for.

    Run this BEFORE a large import: building a 2dsphere index over 5.9M existing
    documents is far slower than maintaining it as they are inserted.
    """
    if explain:
        for spec in db_indexes.describe_indexes():
            keys = ", ".join(f"{name}:{direction}" for name, direction in spec["keys"])
            typer.secho(f"{spec['collection']}.{spec['name']}", fg=typer.colors.CYAN, bold=True)
            typer.echo(f"  keys       {keys}")
            typer.echo(f"  serves     {spec['serves']}")
            typer.echo(f"  write cost {spec['write_cost']}")
            typer.echo("")
        return

    try:
        with sync_database(database_name=database_name) as database:
            typer.echo(f"MongoDB {server_version(database)} - database '{database.name}'")
            created = db_indexes.ensure_indexes(database)
    except typer.Exit:
        raise
    except Exception as exc:
        typer.secho(f"Failed to create indexes: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    for name in created:
        typer.secho(f"  ok  {name}", fg=typer.colors.GREEN)
    typer.secho(f"{len(created)} indexes ensured.", fg=typer.colors.GREEN, bold=True)


@app.command("import")
def import_command(
    source: Annotated[
        Path | None, typer.Option("--source", "-s", help="AIS CSV. Defaults to AIS_DATA_PATH.")
    ] = None,
    database_name: Annotated[
        str | None, typer.Option("--database", help="Override MONGODB_DATABASE.")
    ] = None,
    batch_size: Annotated[
        int,
        typer.Option("--batch-size", min=100, max=100_000, help="Operations per bulk write."),
    ] = DEFAULT_BATCH_SIZE,
    limit: Annotated[
        int | None, typer.Option("--limit", "-n", min=1, help="Stop after N rows.")
    ] = None,
    resume: Annotated[
        bool, typer.Option("--resume", help="Continue the last incomplete run for this file.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Parse and count without writing anything.")
    ] = False,
    ensure_indexes: Annotated[
        bool,
        typer.Option("--ensure-indexes/--no-ensure-indexes", help="Create indexes before load."),
    ] = True,
) -> None:
    """Import AIS observations into MongoDB.

    Streaming, resumable, and idempotent: re-running is safe because each
    position document's _id is a deterministic fingerprint of the observation
    (ADR-0006). Ctrl+C finishes the current batch and checkpoints.
    """
    _install_sigint_handler()
    settings = get_settings()
    path = _resolve_source(source)

    typer.secho(
        f"Importing {path.name} ({path.stat().st_size / 1024**3:.2f} GiB)",
        fg=typer.colors.CYAN,
        bold=True,
    )
    if dry_run:
        typer.secho("  dry run - no writes will be performed", fg=typer.colors.YELLOW)

    typer.echo("  computing source checksum...")
    checksum = file_checksum(path)
    typer.echo(f"  checksum {checksum}")

    try:
        with sync_database(database_name=database_name) as database:
            typer.echo(f"  MongoDB {server_version(database)} - database '{database.name}'")

            if ensure_indexes and not dry_run:
                typer.echo("  ensuring indexes before load...")
                db_indexes.ensure_indexes(database)

            resume_from_row = 0
            if resume:
                found = find_resume_point(database, checksum=checksum)
                if found is None:
                    typer.secho(
                        "  no incomplete run found for this file - starting from the beginning",
                        fg=typer.colors.YELLOW,
                    )
                else:
                    resume_from_row = found[0]
                    typer.secho(f"  resuming after row {resume_from_row:,}", fg=typer.colors.YELLOW)

            run_id = start_run(
                database,
                path=path,
                checksum=checksum,
                dataset=settings.ais_dataset_name,
                batch_size=batch_size,
                limit=limit,
                resume_from_row=resume_from_row,
                dry_run=dry_run,
            )
            typer.echo(f"  run {run_id}")
            typer.echo("")

            started = time.perf_counter()

            def report(stats: IngestionStats) -> None:
                elapsed = time.perf_counter() - started
                rate = stats.rows_read / elapsed if elapsed > 0 else 0.0
                sys.stderr.write(
                    f"\r  {stats.rows_read:>12,} rows | {rate:>8,.0f}/s | "
                    f"ins {stats.positions_inserted:>11,} | "
                    f"dup {stats.positions_duplicate:>6,} | "
                    f"rej {stats.rows_rejected:>6,}"
                )
                sys.stderr.flush()

            try:
                stats = ingest(
                    path,
                    database,
                    dataset=settings.ais_dataset_name,
                    batch_size=batch_size,
                    limit=limit,
                    resume_from_row=resume_from_row,
                    dry_run=dry_run,
                    run_id=run_id,
                    progress=report,
                    should_cancel=was_cancelled,
                )
            except Exception as exc:
                sys.stderr.write("\n")
                finish_run(
                    database, run_id, status="failed", stats=IngestionStats(), error=str(exc)
                )
                typer.secho(f"Import failed: {exc}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=1) from exc

            sys.stderr.write("\r" + " " * 110 + "\r")
            sys.stderr.flush()

            status: RunStatus = "cancelled" if was_cancelled() else "completed"
            finish_run(database, run_id, status=status, stats=stats)

            colour = typer.colors.YELLOW if status == "cancelled" else typer.colors.GREEN
            typer.secho(f"Import {status} in {stats.duration_seconds:,.1f}s", fg=colour, bold=True)
            typer.echo(f"  rows read           {stats.rows_read:,}")
            typer.echo(f"  rows valid          {stats.rows_valid:,}")
            typer.echo(f"  rows rejected       {stats.rows_rejected:,}")
            for reason, count in sorted(stats.reject_reasons.items()):
                typer.echo(f"    {reason:<26} {count:,}")
            typer.echo(f"  positions inserted  {stats.positions_inserted:,}")
            typer.echo(f"  duplicates skipped  {stats.positions_duplicate:,}")
            typer.echo(f"  vessels upserted    {stats.vessels_upserted:,}")
            typer.echo(f"  latest state writes {stats.latest_updated:,}")
            typer.echo(f"  throughput          {stats.rows_per_second:,.0f} rows/s")
    except typer.Exit:
        raise
    except Exception as exc:
        typer.secho(f"Import failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


@app.command("rollup")
def rollup_command(
    database_name: Annotated[
        str | None, typer.Option("--database", help="Override MONGODB_DATABASE.")
    ] = None,
) -> None:
    """Precompute whole-archive analytics.

    Three analytics queries aggregate every stored observation when asked for
    the whole archive, which measured 43.6 s, 38.4 s and 31.8 s here. No index
    makes them selective — the window *is* the dataset — so the answers are
    computed once and stored. See ``app/services/rollup.py`` for the
    measurement and the covering index that was tried and rejected.

    Safe to re-run. Safe to skip: the API falls back to the live aggregation
    and returns the same numbers, slowly. Run it after every import.
    """
    try:
        with sync_database(database_name=database_name) as database:
            typer.echo(f"Building analytics rollups in '{database.name}'")
            summary = rollup_service.build(database)
    except Exception as exc:
        typer.secho(f"Rollup failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if summary.get("built", 0) == 0:
        typer.secho(
            f"Nothing to roll up: {summary.get('reason', 'unknown')}.",
            fg=typer.colors.YELLOW,
        )
        return

    typer.echo("")
    typer.echo(f"  coverage           {summary['coverageStart']} -> {summary['coverageEnd']}")
    typer.echo(f"  source documents   {summary['sourceDocumentCount']:,}")
    for kind, seconds in summary["seconds"].items():
        typer.echo(f"  {kind:<20} {seconds:>8.2f} s")
    typer.echo("")
    typer.secho(f"{summary['built']} rollups written.", fg=typer.colors.GREEN)


@app.command("validate")
def validate_command(
    database_name: Annotated[
        str | None, typer.Option("--database", help="Override MONGODB_DATABASE.")
    ] = None,
) -> None:
    """Verify stored data against the profiler and for internal consistency.

    Exits non-zero if any check fails, so a lossy import cannot pass as a good
    one.
    """
    expected_rows, expected_duplicates = _load_profile_expectations()
    try:
        with sync_database(database_name=database_name) as database:
            typer.echo(f"Validating database '{database.name}'")
            report = validate_import(
                database,
                expected_rows=expected_rows,
                expected_duplicates=expected_duplicates,
            )
    except typer.Exit:
        raise
    except Exception as exc:
        typer.secho(f"Validation failed to run: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("")
    for name, value in report["counts"].items():
        typer.echo(f"  {name:<32} {value:,}")
    time_range = report["timeRange"]
    typer.echo(f"  {'time range':<32} {time_range['min']} .. {time_range['max']}")
    typer.echo("")

    for check in report["checks"]:
        mark = "ok  " if check["ok"] else "FAIL"
        colour = typer.colors.GREEN if check["ok"] else typer.colors.RED
        typer.secho(f"  {mark}  {check['name']}", fg=colour, bold=not check["ok"])
        typer.echo(f"        {check['detail']}")

    typer.echo("")
    if report["ok"]:
        typer.secho("All checks passed.", fg=typer.colors.GREEN, bold=True)
    else:
        typer.secho("Validation FAILED.", fg=typer.colors.RED, bold=True)
        raise typer.Exit(code=1)


@app.command("status")
def status_command(
    database_name: Annotated[
        str | None, typer.Option("--database", help="Override MONGODB_DATABASE.")
    ] = None,
) -> None:
    """Show what is currently loaded and the state of the last ingestion run."""
    try:
        with sync_database(database_name=database_name) as database:
            typer.secho(
                f"MongoDB {server_version(database)} - database '{database.name}'",
                fg=typer.colors.CYAN,
                bold=True,
            )
            typer.echo("")
            for name in db_collections.ALL_COLLECTIONS:
                count = database[name].estimated_document_count()
                typer.echo(f"  {name:<20} {count:>12,} documents")
            typer.echo("")

            run = latest_run(database)
            if run is None:
                typer.secho(
                    "No ingestion run recorded. Run `navisight-data import`.",
                    fg=typer.colors.YELLOW,
                )
                return
            typer.echo(f"  last run    {run['_id']}")
            typer.echo(f"  source      {run.get('sourceFile')}")
            typer.echo(f"  status      {run.get('status')}")
            typer.echo(f"  started     {run.get('startedAt')}")
            typer.echo(f"  completed   {run.get('completedAt')}")
            typer.echo(f"  checkpoint  {run.get('lastCheckpointRow', 0):,}")
            stats = run.get("stats") or {}
            for key in ("rowsRead", "positionsInserted", "positionsDuplicate", "rowsRejected"):
                if key in stats:
                    typer.echo(f"  {key:<12}{stats[key]:>13,}")
    except typer.Exit:
        raise
    except Exception as exc:
        typer.secho(f"Could not read status: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc


if __name__ == "__main__":  # pragma: no cover
    app()
