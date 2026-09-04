# AIS Source Data Reference

Field definitions and valid domains for the AIS broadcast-point data NaviSight
ingests. These are **not** NaviSight's inventions — they are transcribed from
the official data dictionary so that our validation code has a citable
authority rather than a guess.

## Source

- **Publisher:** NOAA Office for Coastal Management / MarineCadastre.gov
  (U.S. Coast Guard AIS broadcast data)
- **Data dictionary:** <https://coast.noaa.gov/data/marinecadastre/ais/data-dictionary.pdf>
  (document dated *Updated: July 31, 2026*; page 2 covers "point data from
  2025 to present", which is the schema NaviSight targets)
- **Portal:** <https://marinecadastre.gov/accessais/>
- **Dataset hub:** <https://hub.marinecadastre.gov/pages/vesseltraffic>

Distribution characteristics stated by the publisher that matter to us:

- Data since 2015 is distributed as **daily CSV files, Zstd-compressed**.
- The point data is **filtered to one-minute resolution**. This is why a vessel
  produces at most roughly one observation per minute rather than a continuous
  stream, and it is the reason NaviSight describes tracks as *sampled
  observations* rather than continuous telemetry.
- **All AIS/NMEA timestamps are UTC.**

## Schema (2025 to present)

This is the schema of `ais-2025-01-08.csv`, verified against the file's actual
header. Column order below is the file's order.

| # | Field | Description | Unit | Valid domain | Null allowed | Source type |
|---|-------|-------------|------|--------------|--------------|-------------|
| 1 | `mmsi` | Maritime Mobile Service Identity | — | `2-7` + MID×3 + 4 digits | **No** | int32 |
| 2 | `base_date_time` | Full **UTC** date and time | — | — | **No** | datetime64 |
| 3 | `longitude` | Longitude | decimal degrees | −179.99999 … 179.99999 | **No** | double |
| 4 | `latitude` | Latitude | decimal degrees | −89.99999 … 89.99999 | **No** | double |
| 5 | `sog` | Speed over ground | knots | 0 … 99.9 | Yes | float |
| 6 | `cog` | Course over ground | degrees | 0 … 359.9 | Yes | float |
| 7 | `heading` | True heading | degrees | 0 … 359 | Yes | int32 |
| 8 | `vessel_name` | Name on the station radio license | — | UTF-8, 24 chars | Yes | string |
| 9 | `imo` | IMO vessel number | — | alphanumeric, 12 chars | Yes | string |
| 10 | `call_sign` | Call sign assigned by the FCC | — | alphanumeric, 8 chars | Yes | string |
| 11 | `vessel_type` | Vessel type per NAIS specification | — | 1 … 1024 † | Yes | int32 |
| 12 | `status` | Navigation status | — | 1 … 14 † ‡ | Yes | int32 |
| 13 | `length` | Vessel length | meters | 1 … 509 | Yes | int32 |
| 14 | `width` | Vessel width | meters | 1 … 61 | Yes | int32 |
| 15 | `draft` | Draft depth | meters | 1 … 24 | Yes | float |
| 16 | `cargo` | Cargo type per NAIS specification | — | 1 … 1024 † | Yes | int32 |
| 17 | `transceiver` | AIS transceiver class | — | `A` \| `B` | Yes | string |

† Marked in the dictionary as requiring an applicable lookup table.

‡ **Known discrepancy — read this before writing validation.** The dictionary
states a `status` domain of 1–14, but ITU-R M.1371 defines navigational status
`0` as *"under way using engine"*, and value `0` occurs in the source file (see
`docs/data/AIS_PROFILE.md` for the measured distribution). NaviSight therefore
**does not reject `status = 0`**. We treat the documented domain as guidance,
report observed values that fall outside it, and preserve the source value
rather than coercing it. This is recorded here rather than silently patched
because a future reader will otherwise re-derive the same confusion.

## How NaviSight applies these domains

The profiler and the ingestion validator use the table above as **reporting**
thresholds, not as a silent filter:

- Values outside a documented domain are **counted and surfaced**, never
  quietly clamped.
- Only records that cannot yield a usable position event are **rejected**:
  unparseable timestamp, unparseable/missing coordinates, or coordinates
  outside the physically valid range (longitude ±180, latitude ±90).
- Optional fields that are empty, unparseable, or out of domain are stored as
  **absent**, never as `0`. A missing heading is missing; it is not north.
- No AIS sentinel conventions (for example heading `511` meaning "not
  available", or SOG `102.3` meaning "not available") are applied unless and
  until they are verified against a cited specification and recorded here. The
  one-minute-filtered MarineCadastre product already blanks most of these,
  which is why the source file uses empty strings rather than sentinels.

See [`DATA_QUALITY.md`](./DATA_QUALITY.md) for what was actually measured in
the development dataset, and
[`ADR-0009`](../adr/0009-treat-source-timestamps-as-utc.md) for the timezone
decision.

## Licensing

AIS data is produced by the U.S. Coast Guard and distributed by NOAA. NaviSight
claims no ownership of it and does not redistribute it — see
[`data/README.md`](../../data/README.md). The MIT license on this repository
covers NaviSight's source code only.
