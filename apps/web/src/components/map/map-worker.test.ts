/**
 * Regression coverage for the blank-map failure.
 *
 * The bug: MapLibre derives its Web Worker URL from the bundled module's own
 * location, which under Next/Turbopack is `/_next/static/chunks/` — a
 * directory with no worker file in it. The request 404s, `new Worker()` does
 * not throw, and every map then waits forever for a worker that never
 * answers. Nothing renders and nothing is logged beyond a MIME-type warning.
 *
 * Two things have to hold for the fix to keep working, and each is asserted
 * here because neither fails loudly on its own:
 *
 * 1. the application tells MapLibre to use a URL it actually serves;
 * 2. that URL, and the module it imports, exist in `public/`.
 *
 * (2) is a filesystem check rather than a mock, because the whole failure mode
 * was a URL that looked right and was not there.
 */

import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";

import { beforeEach, describe, expect, it, vi } from "vitest";

const setWorkerUrl = vi.hoisted(() => vi.fn());
vi.mock("maplibre-gl", () => ({ setWorkerUrl }));

const webRoot = resolve(__dirname, "..", "..", "..");
const publicDir = join(webRoot, "public");

async function loadFreshModule() {
  vi.resetModules();
  return import("./map-worker");
}

describe("configureMapWorker", () => {
  beforeEach(() => {
    setWorkerUrl.mockClear();
  });

  it("points MapLibre at a worker served from this application's origin", async () => {
    const { configureMapWorker, MAP_WORKER_URL } = await loadFreshModule();

    configureMapWorker();

    expect(setWorkerUrl).toHaveBeenCalledWith(MAP_WORKER_URL);
    // A root-relative path, so it is same-origin and needs no blob shim. If
    // this ever becomes a `/_next/` path the original bug is back.
    expect(MAP_WORKER_URL.startsWith("/")).toBe(true);
    expect(MAP_WORKER_URL.startsWith("/_next/")).toBe(false);
  });

  it("only configures MapLibre once, however many maps mount", async () => {
    const { configureMapWorker } = await loadFreshModule();

    configureMapWorker();
    configureMapWorker();
    configureMapWorker();

    expect(setWorkerUrl).toHaveBeenCalledTimes(1);
  });
});

describe("staged worker assets", () => {
  it("serves the worker at the URL the application asks for", async () => {
    const { MAP_WORKER_URL } = await loadFreshModule();

    const staged = join(publicDir, MAP_WORKER_URL.replace(/^\//, ""));
    expect(
      existsSync(staged),
      `${MAP_WORKER_URL} is not in public/. Run \`pnpm sync:map-worker\`.`,
    ).toBe(true);
  });

  it("also serves the module the worker imports", async () => {
    const { MAP_WORKER_URL } = await loadFreshModule();

    const staged = join(publicDir, MAP_WORKER_URL.replace(/^\//, ""));
    const source = readFileSync(staged, "utf8");

    // The worker pulls its shared runtime in with a relative specifier, so a
    // missing sibling 404s exactly like the original bug did.
    const imports = [...source.matchAll(/from\s*["'](\.[^"']+)["']/g)].map(
      (match) => match[1]!,
    );
    expect(imports.length).toBeGreaterThan(0);

    for (const specifier of imports) {
      const sibling = resolve(dirname(staged), specifier);
      expect(existsSync(sibling), `${specifier} is missing next to the worker`).toBe(true);
    }
  });

  it("stages the worker from the installed maplibre-gl, not a stale copy", async () => {
    const { MAP_WORKER_URL } = await loadFreshModule();

    const require = createRequire(import.meta.url);
    const packageRoot = dirname(require.resolve("maplibre-gl/package.json"));
    const installed = join(packageRoot, "dist", "maplibre-gl-worker.mjs");
    const staged = join(publicDir, MAP_WORKER_URL.replace(/^\//, ""));

    expect(
      readFileSync(staged),
      "public/maplibre is out of date with node_modules. Run `pnpm sync:map-worker`.",
    ).toEqual(readFileSync(installed));
  });
});
