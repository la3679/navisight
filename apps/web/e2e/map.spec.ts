import { expect, test } from "@playwright/test";

/**
 * The map actually draws.
 *
 * This file is the regression guard for the bug that cost two sessions
 * (ADR-0010). MapLibre derives its Web Worker URL from `import.meta.url`; under
 * Turbopack that resolved to a chunk path that 404s. `new Worker(url)` does
 * **not** throw on a 404, so the only symptom was a MIME-type line in the
 * console — and MapLibre then waited forever. Every unit test passed. The build
 * passed. The map was blank.
 *
 * So these assertions are deliberately about *requests and pixels*, not about
 * components mounting:
 *
 * 1. the worker file is served, with a JavaScript content type;
 * 2. a WebGL canvas exists and has non-trivial dimensions;
 * 3. the viewport query ran and returned marks — the readout says how many;
 * 4. the composited canvas is not a flat image;
 * 5. the "basemap could not be drawn" deadline warning is absent.
 *
 * (3) is the closest assertion to the actual defect. `readViewport()` was gated
 * behind `map.on("load")`, which never fired, so no query ever ran and deck.gl
 * received an empty layer array. A non-zero count proves that chain end to end.
 *
 * (4) needs care. Reading pixels back with `drawImage` does **not** work here:
 * MapLibre runs with `preserveDrawingBuffer: false`, so the buffer is empty
 * outside the render frame and a perfectly healthy map reads as one flat
 * colour — a false failure this suite hit before the technique was changed.
 * Playwright's own screenshot captures the composited frame instead, and PNG
 * size is then a sound proxy: a flat image compresses to a few hundred bytes,
 * whereas coastlines and vessel marks do not compress at all well.
 */

test("the MapLibre worker is served from our own origin, not 404ing", async ({ request }) => {
  const response = await request.get("/maplibre/maplibre-gl-worker.mjs");

  expect(
    response.status(),
    "the worker 404s — run `pnpm sync:map-worker`, and see ADR-0010",
  ).toBe(200);
  expect(response.headers()["content-type"]).toMatch(/javascript/);

  // The worker imports a sibling module. Staging one without the other fails
  // the same way, and just as silently.
  const shared = await request.get("/maplibre/maplibre-gl-shared.mjs");
  expect(shared.status()).toBe(200);
});

test("the operations map queries its viewport and draws the result", async ({ page }) => {
  await page.goto("/operations");

  const canvas = page.locator("canvas.maplibregl-canvas").first();
  await expect(canvas).toBeVisible();

  const box = await canvas.boundingBox();
  expect(box?.width ?? 0).toBeGreaterThan(200);
  expect(box?.height ?? 0).toBeGreaterThan(200);

  // The readout is fed by the same query deck.gl renders from. A number here
  // means `readViewport()` ran, the request completed, and marks exist — the
  // exact chain that was broken.
  //
  // Polled rather than read once: the readout renders "0 of 0" before the first
  // query resolves, so a single read races the fetch and fails on a healthy map.
  const readout = page.getByText(/vessels in view|aggregated into/i);
  await expect(readout).toBeVisible({ timeout: 30_000 });
  await expect
    .poll(
      async () => Number(/(\d+)/.exec((await readout.textContent()) ?? "")?.[1] ?? 0),
      { timeout: 30_000, message: "the viewport query returned no vessels" },
    )
    .toBeGreaterThan(0);

  await expect(page.getByText(/loading vessels/i)).toHaveCount(0, { timeout: 30_000 });

  // See the header: PNG size, not a pixel readback.
  const png = await canvas.screenshot();
  expect(
    png.byteLength,
    "the map canvas compressed to almost nothing — it is blank (see ADR-0010)",
  ).toBeGreaterThan(5_000);
});

test("the map does not report its basemap deadline", async ({ page }) => {
  // The deadline exists to turn an indefinite silent wait into a visible
  // warning. Seeing it here means the worker regression is back.
  await page.goto("/operations");
  await page.waitForTimeout(14_000);
  await expect(page.getByText(/basemap could not be drawn/i)).toHaveCount(0);
});

test("a vessel can be opened from the fleet list and its track drawn", async ({ page }) => {
  await page.goto("/vessels");

  const firstVessel = page.getByRole("link", { name: /SYNTHETIC|MMSI|IGNORE PRIOR/i }).first();
  await expect(firstVessel).toBeVisible({ timeout: 30_000 });
  await firstVessel.click();

  await expect(page).toHaveURL(/\/vessels\/\d+/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  // The detail map broke in exactly the same way and only looked healthier
  // because its DOM markers render without a basemap.
  await expect(page.locator("canvas.maplibregl-canvas").first()).toBeVisible({
    timeout: 30_000,
  });
});
