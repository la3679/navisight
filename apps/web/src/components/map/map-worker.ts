/**
 * Point MapLibre at a worker URL this application actually serves.
 *
 * MapLibre's default worker URL is derived from the bundled module's own
 * location, which under Next/Turbopack is `/_next/static/chunks/…` — a
 * directory that contains no worker file. The request 404s, the worker never
 * starts, and every map silently hangs before its first source finishes
 * loading. `scripts/sync-map-worker.mjs` stages the real worker under
 * `public/maplibre/`; this module tells MapLibre to use it.
 *
 * Call {@link configureMapWorker} before constructing any map.
 */

import { setWorkerUrl } from "maplibre-gl";

/** Where `scripts/sync-map-worker.mjs` stages the worker bundle. */
export const MAP_WORKER_URL = "/maplibre/maplibre-gl-worker.mjs";

let configured = false;

/**
 * Idempotently install the worker URL.
 *
 * MapLibre reads the URL each time it spawns a worker, so this only has to run
 * before the first map is created — but it is cheap and safe to call from
 * every map component, which is what keeps a future third map from
 * reintroducing the bug.
 */
export function configureMapWorker(): void {
  if (configured) return;
  setWorkerUrl(MAP_WORKER_URL);
  configured = true;
}

/**
 * How long a map may sit unloaded before we call it broken.
 *
 * The bundled ground is ~94 KB from our own origin, so a healthy load is far
 * under a second even on a cold cache. This ceiling exists to convert the
 * worker failure mode — an indefinite silent wait — into a visible error, per
 * SOUL.md §5 ("no swallowed failures") and §11 ("a blank panel is a bug").
 */
export const MAP_LOAD_TIMEOUT_MS = 12_000;
