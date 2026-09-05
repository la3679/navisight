/**
 * Capture the documentation screenshots from the running application.
 *
 * Every image in `docs/screenshots/` is produced by this script, against a
 * NaviSight that is actually serving the real imported archive. That is the
 * whole point: a screenshot is a claim about what the product does, and a
 * mocked or hand-edited one is a false claim that survives longer than any
 * other kind (SOUL.md §9).
 *
 * Two guards enforce that, and both abort rather than warn:
 *
 * - The dataset must not be the synthetic end-to-end fixture. That fixture is
 *   labelled `SYNTHETIC (e2e fixture)` precisely so it can be detected here.
 * - The archive must hold data. Screenshotting empty states as if they were
 *   the product would be the same lie by omission.
 *
 * The copilot capture asks a real question through the configured provider, so
 * running it with `LLM_PROVIDER=openai` spends a fraction of a cent and
 * produces a genuine answer with its genuine evidence. With no provider
 * configured the copilot capture is skipped, not faked.
 *
 * Usage, with the API and the web app already running against the real import:
 *
 *     cd apps/web
 *     pnpm screenshots
 *
 * Environment: WEB_URL (default http://localhost:3000),
 * API_URL (default http://localhost:8000), OUT_DIR (default docs/screenshots).
 */

import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, "..", "..", "..");

const WEB_URL = process.env.WEB_URL ?? "http://localhost:3000";
const API_URL = process.env.API_URL ?? "http://localhost:8000";
const OUT_DIR = process.env.OUT_DIR ?? path.join(REPO_ROOT, "docs", "screenshots");

/** Desktop. 1440x900 is the common laptop viewport and reads well inline. */
const DESKTOP = { width: 1440, height: 900 };

/**
 * 1, not 2. A retina capture doubles every file for detail nobody reads at the
 * width GitHub renders a README image, and these are committed assets.
 */
const SCALE = 1;

/** WebGL needs a real rasteriser; CI runners and this machine may lack a GPU. */
const LAUNCH_ARGS = ["--use-gl=swiftshader", "--enable-unsafe-swiftshader"];

/** Long enough for a map style, a viewport query, and a first WebGL frame. */
const SETTLE_MS = 4_000;

const SHOTS = [
  {
    file: "operations-map.png",
    path: "/operations",
    caption: "Every vessel's last archived position, aggregated by viewport.",
    settleMs: 9_000,
  },
  {
    file: "home-overview.png",
    path: "/",
    caption: "The overview, with the archive's measured figures.",
    settleMs: 7_000,
  },
  {
    file: "analytics.png",
    path: "/analytics",
    caption: "Traffic, fleet composition and speed across the archived day.",
    settleMs: 6_000,
  },
  {
    file: "vessel-detail.png",
    path: "/vessels/338078000",
    caption: "One vessel: its track, its record, and a hull built from its own dimensions.",
    settleMs: 8_000,
  },
  {
    file: "vessel-3d-inspector.png",
    path: "/vessels/338078000",
    caption:
      "A generic hull scaled to the vessel's own reported dimensions — labelled as " +
      "representative, because it is not a model of that ship.",
    // The inspector sits below the fold on a 900px viewport.
    scrollTo: "text=Representative visualisation",
    settleMs: 8_000,
  },
  {
    file: "dataset.png",
    path: "/data",
    caption: "What was imported, reconciled against an independent profiling pass.",
    settleMs: 4_000,
  },
];

async function assertRealDataset() {
  const response = await fetch(`${API_URL}/api/v1/dataset/status`);
  if (!response.ok) {
    throw new Error(`The API at ${API_URL} answered ${response.status}. Is it running?`);
  }
  const status = await response.json();

  if (!status.hasData) {
    throw new Error("The archive is empty. Screenshots of empty states are not documentation.");
  }
  if (/synthetic/i.test(String(status.dataset))) {
    throw new Error(
      `The API is serving '${status.dataset}'. That is the end-to-end fixture, and its ` +
        "figures are invented. Point MONGODB_DATABASE at the real import and try again.",
    );
  }

  console.log(
    `Dataset: ${status.dataset} — ${status.counts.positions.toLocaleString()} positions, ` +
      `${status.counts.vessels.toLocaleString()} vessels, ${status.coverage.start} to ` +
      `${status.coverage.end}`,
  );
  return status;
}

async function aiConfigured() {
  const response = await fetch(`${API_URL}/api/v1/agent/status`);
  if (!response.ok) return null;
  const status = await response.json();
  return status.configured ? status : null;
}

async function capture(page, shot) {
  await page.goto(`${WEB_URL}${shot.path}`, { waitUntil: "networkidle" });
  if (shot.scrollTo) {
    // `scrollIntoViewIfNeeded` decides nothing is needed when the element is
    // already a sliver above the fold, which is exactly the case here.
    await page
      .locator(shot.scrollTo)
      .first()
      .evaluate((element) => element.scrollIntoView({ block: "center" }));
  }
  await page.waitForTimeout(shot.settleMs ?? SETTLE_MS);
  const file = path.join(OUT_DIR, shot.file);
  await page.screenshot({ path: file, scale: "css" });
  console.log(`  wrote ${path.relative(REPO_ROOT, file)}`);
}

async function captureCopilot(page, question) {
  await page.goto(`${WEB_URL}/copilot`, { waitUntil: "networkidle" });
  await page.getByRole("textbox").fill(question);
  await page.getByRole("button", { name: /^ask$/i }).click();

  // The answer is a real model round trip. Wait for the evidence list, which
  // only renders once a run has completed.
  await page.getByText(/tools? ran/i).waitFor({ timeout: 90_000 });
  await page.waitForTimeout(1_000);

  const file = path.join(OUT_DIR, "copilot-answer.png");
  await page.screenshot({ path: file, scale: "css" });
  console.log(`  wrote ${path.relative(REPO_ROOT, file)}`);
}

async function main() {
  const dataset = await assertRealDataset();
  const ai = await aiConfigured();

  await mkdir(OUT_DIR, { recursive: true });

  const browser = await chromium.launch({ args: LAUNCH_ARGS });
  const context = await browser.newContext({
    viewport: DESKTOP,
    deviceScaleFactor: SCALE,
    // The application's own default. next-themes resolves the system
    // preference, so this is what decides light or dark.
    colorScheme: "dark",
  });
  const page = await context.newPage();

  console.log(`Capturing ${SHOTS.length} screens at ${DESKTOP.width}x${DESKTOP.height}:`);
  for (const shot of SHOTS) {
    await capture(page, shot);
  }

  const question =
    "Which vessel types are most common in this archive, and which vessels broadcast the most?";
  if (ai) {
    console.log(`Asking the copilot through ${ai.provider}/${ai.model}:`);
    await captureCopilot(page, question);
  } else {
    console.log(
      "No AI provider configured — skipping the copilot capture rather than faking it.",
    );
  }

  await browser.close();

  const manifest = {
    capturedAt: new Date().toISOString(),
    viewport: DESKTOP,
    deviceScaleFactor: SCALE,
    colorScheme: "dark",
    dataset: {
      name: dataset.dataset,
      positions: dataset.counts.positions,
      vessels: dataset.counts.vessels,
      coverage: dataset.coverage,
    },
    copilot: ai ? { provider: ai.provider, model: ai.model, question } : null,
    images: [
      ...SHOTS.map((shot) => ({ file: shot.file, route: shot.path, caption: shot.caption })),
      ...(ai
        ? [
            {
              file: "copilot-answer.png",
              route: "/copilot",
              caption: `A real answer from ${ai.provider}/${ai.model}, with the tool calls behind it.`,
            },
          ]
        : []),
    ],
  };
  const manifestPath = path.join(OUT_DIR, "manifest.json");
  await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  console.log(`  wrote ${path.relative(REPO_ROOT, manifestPath)}`);
}

await main();
