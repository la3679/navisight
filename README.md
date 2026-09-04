<div align="center">

# NaviSight

**Maritime Vessel & Port Intelligence Platform**

Explore vessel movement. Investigate traffic. Ask the data.

</div>

---

> **Build status — this README is under construction.**
> The repository is being built out phase by phase. Sections below describe
> what exists *today*; anything not yet implemented is marked. No performance
> number, row count, or benchmark appears in this document unless it was
> actually measured by tooling in this repository.

## What NaviSight is

NaviSight ingests real **historical** AIS vessel-position broadcasts — millions
of them — into MongoDB, and makes that movement record explorable three ways:

1. **Spatially**, through a maritime operations map with geospatial querying.
2. **Analytically**, through MongoDB aggregations over traffic and vessel activity.
3. **Conversationally**, through an AI copilot that answers by calling
   allow-listed, typed data tools and shows you the evidence behind every claim.

It is a personal portfolio engineering project modeled on real maritime
intelligence systems. It has no production users and is not deployed on behalf
of any organization.

## What NaviSight is not

- Not a navigation, collision-avoidance, or safety-critical system.
- Not real-time. The dataset is a **single historical day** of AIS broadcasts,
  filtered by the publisher to one-minute resolution. The UI says
  "historical replay" and "latest observation in dataset" because that is what
  the data is.
- Not a claim of ownership over public AIS data.

## Dataset

U.S. Coast Guard AIS broadcast points, distributed by NOAA / MarineCadastre.
Development uses the daily file for **2025-01-08**.

The raw CSV is **not committed** — see [`data/README.md`](data/README.md) for
how to obtain it and where to put it, and
[`docs/data/AIS_SOURCE_REFERENCE.md`](docs/data/AIS_SOURCE_REFERENCE.md) for the
field-level schema and documented valid domains.

## Engineering principles

Non-negotiables for this codebase live in [`SOUL.md`](SOUL.md). The short
version: model MongoDB for access patterns, never fabricate a number, never
call historical data live, never let an LLM author a database query, and never
commit the dataset.

## Documentation

| Area | Document |
|------|----------|
| Engineering constitution | [`SOUL.md`](SOUL.md) |
| AIS source schema | [`docs/data/AIS_SOURCE_REFERENCE.md`](docs/data/AIS_SOURCE_REFERENCE.md) |
| Decision records | [`docs/adr/`](docs/adr/) |
| Data directory / provenance | [`data/README.md`](data/README.md) |
| Security policy | [`SECURITY.md`](SECURITY.md) |
| Contributing | [`CONTRIBUTING.md`](CONTRIBUTING.md) |

More documentation is added as each subsystem lands.

## License

[MIT](LICENSE), covering NaviSight's source code only. Source data and
third-party assets carry their own terms — see [`data/README.md`](data/README.md)
and [`docs/THIRD_PARTY_ASSETS.md`](docs/THIRD_PARTY_ASSETS.md).
