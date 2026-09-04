#!/usr/bin/env node
/**
 * Copy MapLibre's Web Worker bundle into `public/maplibre/`.
 *
 * WHY THIS EXISTS
 *
 * maplibre-gl ships its worker as a separate ES module and locates it at
 * runtime with, effectively:
 *
 *     new URL("./maplibre-gl-worker.mjs", import.meta.url)
 *
 * That resolves relative to wherever the bundler put the main module. Under
 * Next/Turbopack the library lands in `/_next/static/chunks/`, where no such
 * sibling file exists, so the URL 404s. Because the URL is built from a
 * template string rather than a literal, no bundler can see it and emit the
 * worker chunk either.
 *
 * The failure is silent and total: `new Worker(url, {type:"module"})` does not
 * throw, the browser only logs a MIME-type complaint, and MapLibre then waits
 * forever for a worker that will never answer. No source ever finishes
 * loading, `map.on("load")` never fires, and the canvas stays blank.
 *
 * So we serve the worker ourselves. Copying it here — rather than reaching
 * into `node_modules` at runtime — keeps the asset on our own origin (no
 * cross-origin blob shim) and keeps it working identically in dev, in a
 * production build, and in CI.
 *
 * `maplibre-gl-shared.mjs` comes along because the worker imports it with a
 * relative specifier and would 404 the same way without it.
 *
 * The destination is generated, not authored: it is git-ignored and rewritten
 * from the installed package whenever the version changes.
 */

import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const webRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const destinationDir = join(webRoot, "public", "maplibre");

/** Files the worker needs, in the order they are checked. */
const ASSETS = ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"];

/** The marker records what was copied, so a no-op run stays cheap. */
const MARKER = "SOURCE.json";

async function main() {
  const packageJsonPath = require.resolve("maplibre-gl/package.json");
  const packageRoot = dirname(packageJsonPath);
  const { version } = JSON.parse(await readFile(packageJsonPath, "utf8"));

  const sources = ASSETS.map((name) => join(packageRoot, "dist", name));
  const fingerprint = createHash("sha256");
  for (const source of sources) {
    // Read rather than stat: a truncated or replaced file must invalidate the
    // marker, and these are small enough that reading them is free.
    fingerprint.update(await readFile(source));
  }
  const expected = { version, digest: fingerprint.digest("hex"), assets: ASSETS };

  const markerPath = join(destinationDir, MARKER);
  try {
    const current = JSON.parse(await readFile(markerPath, "utf8"));
    if (current.version === expected.version && current.digest === expected.digest) {
      return `maplibre worker assets already current (v${version})`;
    }
  } catch {
    // No marker, or an unreadable one. Copy.
  }

  await mkdir(destinationDir, { recursive: true });
  for (const [index, name] of ASSETS.entries()) {
    await copyFile(sources[index], join(destinationDir, name));
  }
  await writeFile(markerPath, `${JSON.stringify(expected, null, 2)}\n`, "utf8");

  return `copied maplibre worker assets (v${version}) to public/maplibre/`;
}

try {
  console.log(await main());
} catch (error) {
  // Failing loudly matters: a silent skip here reproduces exactly the blank
  // map this script exists to prevent.
  console.error(
    "Failed to stage MapLibre worker assets. The map will not render without " +
      "them.\n" +
      (error instanceof Error ? error.message : String(error)),
  );
  process.exit(1);
}
