# Third-Party Assets

Everything NaviSight redistributes that it did not author, with its source and
licence. The MIT licence on this repository covers NaviSight's **source code
only** — it does not relicense anything on this page.

## Policy

From SOUL.md §15 and the asset rules in the build spec:

1. **Prefer generating over downloading.** Where an asset can be produced from
   geometry in code, it is.
2. **No unverified assets.** Nothing is added without a checked licence, a
   recorded source URL, and an author.
3. **No large binaries.** Assets are minified and size-checked before they are
   committed.

## 3D models — none

**NaviSight bundles no third-party 3D models.** Every mesh in the application
is generated procedurally from Three.js geometry primitives in
[`apps/web/src/components/three/`](../apps/web/src/components/three/).

The vessel hull in `vessel-hull.tsx` is built by extruding a `THREE.Shape`
whose outline is computed from the vessel's own AIS-reported length, beam, and
draft, with superstructure placement following broad conventions per vessel
type. That is a deliberate choice with real benefits:

- no licensing or attribution risk from a downloaded model of uncertain origin;
- a few kilobytes of vertices instead of a multi-megabyte GLB;
- the geometry responds to the actual data rather than being a fixed prop.

The trade-off is that the models are **representative silhouettes, not
likenesses** of specific ships. Every surface that displays one says so.

## Map data

### Natural Earth — coastlines and land polygons

| | |
|---|---|
| **File** | `apps/web/public/geo/ne_110m_land.json` (~94 KB) |
| **Source** | Natural Earth 1:110m "land" vector layer, via <https://github.com/nvkelso/natural-earth-vector> |
| **Home** | <https://www.naturalearthdata.com/> |
| **Licence** | **Public domain.** Natural Earth states: "All versions of Natural Earth raster + vector map data found on this website are in the public domain." No permission or attribution is required. |
| **Modifications** | Feature properties stripped; coordinates rounded to 3 decimal places (~110 m), reducing 135 KB to 94 KB. Geometry is otherwise unaltered. |
| **Why bundled** | It lets the map render coastlines with **no request to any external tile host** — so the map works offline and in CI, and opening it does not disclose the user's viewport to a third party. |

Attribution is displayed on the map anyway, as a courtesy rather than an
obligation: *"Coastlines: Natural Earth (public domain)"*.

The trade-off is resolution: 1:110m gives continental outlines, not harbour
detail. Setting `NEXT_PUBLIC_MAP_STYLE_URL` swaps in any MapLibre style you
have the rights to use.

## Source data

AIS broadcast data is collected by the U.S. Coast Guard and distributed by the
NOAA Office for Coastal Management. NaviSight **does not redistribute it** — the
raw file is not in this repository (see
[ADR-0007](adr/0007-keep-large-ais-data-out-of-git.md) and
[`data/README.md`](../data/README.md)). Only derived aggregate statistics are
published, under [`docs/data/`](data/).

- Portal: <https://marinecadastre.gov/accessais/>
- Data dictionary: <https://coast.noaa.gov/data/marinecadastre/ais/data-dictionary.pdf>

## Fonts

| Font | Source | Licence |
|---|---|---|
| Inter | Google Fonts, via `next/font` | SIL Open Font License 1.1 |
| JetBrains Mono | Google Fonts, via `next/font` | SIL Open Font License 1.1 |

Both are self-hosted at build time by `next/font`, so no request is made to
Google at runtime.

## Icons

[Lucide](https://lucide.dev/) — **ISC License**. Used as a React component
dependency; no icon files are vendored into this repository.

## Adding an asset

Before committing one, record here: the file path, the source URL, the author
or publisher, the exact licence, any modifications made, and the reason it is
bundled rather than generated. If any of those cannot be established, the asset
does not go in.
