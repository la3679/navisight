# Data directory

## The raw AIS dataset is not in this repository — by design

NaviSight is developed against a daily AIS broadcast-point file of roughly
**577 MiB / 5.9 million rows**. That file is deliberately kept **outside** the
repository and is never committed, for the reasons recorded in
[ADR-0007](../docs/adr/0007-keep-large-ais-data-out-of-git.md):

- Git stores full history; a large binary-ish CSV would permanently bloat every
  clone, and Git LFS would push that cost onto anyone who forks the project.
- NaviSight does not own the data and should not redistribute it.
- The pipeline's job is to be reproducible from the *original* source, not to
  ship a private copy of it.

`.gitignore` blocks `ais-*.csv` by name so an accidental copy cannot be staged.

## Getting the dataset

1. Go to **MarineCadastre AccessAIS**: <https://marinecadastre.gov/accessais/>
   (dataset hub: <https://hub.marinecadastre.gov/pages/vesseltraffic>).
2. Download a daily AIS broadcast-points file. Development used
   **2025-01-08**. Files are distributed Zstd-compressed; decompress to CSV.
3. Place the CSV **outside** the repository — the convention is a sibling of
   the repo directory:

   ```text
   VS Code Projects/
   ├── ais-2025-01-08.csv     <- here
   └── navisight/             <- this repository
   ```

4. Point `AIS_DATA_PATH` at it in your `.env`:

   ```dotenv
   AIS_DATA_PATH=../ais-2025-01-08.csv
   ```

Any daily file with the 2025+ schema works. The schema NaviSight expects, and
its documented valid domains, are transcribed in
[`docs/data/AIS_SOURCE_REFERENCE.md`](../docs/data/AIS_SOURCE_REFERENCE.md).

NaviSight never writes to the source file. It is treated as immutable input.

## What *is* committed here

| Path | Contents |
|------|----------|
| `samples/` | Small, hand-checkable synthetic AIS fixtures with the real schema. Used by tests and by anyone who wants to run the pipeline without downloading 577 MiB. Synthetic — no real vessel appears here. |
| `reference/` | Small reference lookups (for example port reference data, once configured). Large downloads land here and are git-ignored; only the loader and a `.gitkeep` are tracked. |

## Port reference data (optional)

NaviSight ships **no port gazetteer**, and does not derive one from the AIS
data. The source contains no port information, and inventing place names to sit
beside real vessel positions is exactly the fabrication
[SOUL.md §9](../SOUL.md) forbids. Until you load one, every port surface reports
`PORT_DATA_NOT_CONFIGURED` and explains what to do — which is a different
statement from an empty list.

Bring your own registry. The U.S. NGA **World Port Index** is public domain and
maps onto the schema below directly; any other gazetteer you have the rights to
use works equally well.

```bash
cd apps/api
uv run navisight-data ports load ../../data/reference/your-ports.csv
uv run navisight-data ports clear          # remove it again
```

### Schema

CSV columns (a `FeatureCollection` of GeoJSON points works too, with the same
property names):

| Column | Required | Notes |
|---|---|---|
| `id` | yes | Stable identifier; re-loading updates in place by this key. |
| `name` | yes | |
| `latitude` | yes | Decimal degrees, −90…90. |
| `longitude` | yes | Decimal degrees, −180…180. |
| `country` | no | |
| `unlocode` | no | |
| `harbourSize` | no | Free text as the registry states it. |
| `harbourType` | no | Free text as the registry states it. |

Any other column is ignored, so a fifty-column export needs no preprocessing.

A malformed row **aborts the load** rather than being skipped: a port list is
small and hand-fixable, and silently dropping entries would leave you believing
you had loaded a complete registry.

Loaded files belong in `reference/` and are git-ignored — NaviSight does not
redistribute someone else's registry any more than it redistributes the AIS
file.

Derived **statistics** about the real dataset — row counts, null rates,
distributions — are committed under `docs/data/`. Those are aggregates, not
data, and they are what makes the profiling claims in the README verifiable.

## Licensing

AIS broadcast data is collected by the U.S. Coast Guard and distributed by the
NOAA Office for Coastal Management. NaviSight claims no ownership of it. The
MIT license in this repository applies to NaviSight's source code only, not to
the source data or to third-party assets (see
[`docs/THIRD_PARTY_ASSETS.md`](../docs/THIRD_PARTY_ASSETS.md)).
