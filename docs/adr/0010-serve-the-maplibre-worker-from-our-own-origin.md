# ADR-0010: Serve MapLibre's Web Worker from our own `public/` directory

- **Status:** Accepted
- **Date:** 2026-09-04

## Context

maplibre-gl 6.7.0 ships its Web Worker as a separate ES module rather than
inlining it, and locates it at runtime from the main bundle's own position:

```js
new URL(`./${workerName}`, import.meta.url)
```

Under Next 16 with Turbopack the library is served from `/_next/static/chunks/`,
which contains no sibling worker file, so that URL 404s. Because the specifier
is assembled from a template string, no bundler can see it statically and emit
the worker chunk either.

The resulting failure is total and silent. `new Worker(url, {type: "module"})`
does not throw on a 404; the browser only logs a MIME-type complaint about the
HTML it received instead of JavaScript. MapLibre then waits indefinitely for a
worker that will never answer: `Style.loadJSON` never resolves, no source ever
finishes, `map.on("load")` never fires, and the canvas stays empty.

This is what made the operations map render nothing. It looked like a deck.gl
integration fault — deck.gl was the only thing the working-looking vessel-detail
map did not do — but both maps were broken by the same missing worker, and the
vessel layer was empty only because the viewport query was gated behind a `load`
event that could never arrive.

## Decision

Copy `maplibre-gl-worker.mjs`, and the `maplibre-gl-shared.mjs` it imports, from
the installed package into `apps/web/public/maplibre/`, and call
`setWorkerUrl("/maplibre/maplibre-gl-worker.mjs")` at module scope in every file
that constructs a map.

`apps/web/scripts/sync-map-worker.mjs` performs the copy. It runs as the first
step of both `pnpm dev` and `pnpm build` — chained with `&&` in the script
itself rather than relying on a `pre` hook, because pnpm does not run those by
default. It is a no-op when a recorded version-and-digest marker still matches
the installed package, and it exits non-zero if the source files are missing,
because a silent skip here reproduces exactly the blank map it exists to
prevent.

The destination is generated, not authored: git-ignored, Prettier-ignored, and
ESLint-ignored.

Separately, the operations map now issues its viewport query as soon as the map
instance exists rather than waiting for `load`. Vessel marks are deck.gl
geometry projected from the camera and need no basemap tile, so a ground failure
must not be able to masquerade as an empty dataset. If the ground has not
finished after a deadline, the map says so on screen instead of staying blank.

## Alternatives considered

**Leave the default and let MapLibre fall back.** There is no fallback. The
default path is a 404 and the library has no recovery from it.

**Point `setWorkerUrl` at a Next route handler that streams the file out of
`node_modules`.** Rejected: it makes a static asset into a server route, breaks
under static export, and still has to solve the worker's own relative import of
`maplibre-gl-shared.mjs`.

**Commit the worker files into `public/`.** Rejected: two 500 KB vendored blobs
in the tree that silently drift from the installed version on every upgrade.
Generating them makes the version skew impossible instead of merely unlikely.

**Pin maplibre-gl back to a version that inlines its worker.** Rejected: it
trades a build step for staying behind on a rendering dependency, and the same
problem returns at the next upgrade.

## Consequences

**Accepted costs:**

- A build step now stands between a fresh clone and a working map. Running
  `next dev` directly, bypassing `pnpm dev`, produces a blank map.
- ~511 KB of generated files in `public/` that are not in the repository, so a
  deployment pipeline must run `pnpm build` rather than only `next build`.
- Two vendor filenames are now hard-coded in our build script and will need
  attention if MapLibre renames or restructures its distribution.

**Benefits realised:**

- Both maps render. Verified in Chrome: `/operations` draws Natural Earth
  coastlines with GPU vessel marks, aggregating into cells when zoomed out and
  resolving to individual pickable vessels when zoomed in; `/vessels/[mmsi]`
  draws the track line.
- The worker is same-origin, so it needs no cross-origin blob shim and leaks
  nothing to a third party — consistent with the offline-basemap choice.
- `src/components/map/map-worker.test.ts` fails if the staged files go missing
  or drift from `node_modules`, which is the only way this regression can
  return.
