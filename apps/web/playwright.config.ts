import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests: a real browser, the real API, and a synthetic archive.
 *
 * These exist to catch the class of failure the unit tests structurally cannot.
 * The blank-map bug (ADR-0010) is the worked example: MapLibre's Web Worker
 * 404'd under Turbopack, `new Worker()` did not throw, and the only symptom was
 * a console line. Every unit test passed, `pnpm build` passed, and the map was
 * blank. Nothing short of a real browser rendering a real canvas would have
 * caught it.
 *
 * ## Two servers, started by Playwright
 *
 * The API and the web app are both launched here rather than assumed running,
 * so `pnpm e2e` is one command locally and one step in CI. The API is bound to
 * 127.0.0.1 and reads `MONGODB_DATABASE` from the environment — in CI that is
 * `navisight_e2e`, holding the synthetic fixture from
 * `scripts/data/seed_e2e_dataset.py` and never the real import.
 *
 * ## Chromium only
 *
 * The product's hard parts are WebGL: deck.gl over MapLibre, and react-three-fiber.
 * A three-browser matrix would triple the runtime to re-assert the same
 * application logic against three GPU stacks, none of which this project
 * controls. Cross-browser rendering is a real concern and is not addressed
 * here; that is a stated gap, not an oversight.
 */

const WEB_PORT = 3100;
const API_PORT = 8100;
const WEB_URL = `http://127.0.0.1:${WEB_PORT}`;
const API_URL = `http://127.0.0.1:${API_PORT}`;

export default defineConfig({
  testDir: "./e2e",
  // Generous: the first navigation compiles a route, and the map waits on a
  // style load plus a viewport query against MongoDB.
  timeout: 60_000,
  expect: { timeout: 15_000 },

  // A test that passes on retry is still a bug, so retries are for CI's noisier
  // machines only — locally a flake must be visible.
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  forbidOnly: !!process.env.CI,

  reporter: process.env.CI ? [["html", { open: "never" }], ["github"]] : [["list"]],

  use: {
    baseURL: WEB_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "off",
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Software WebGL: CI runners have no GPU, and without this every
        // canvas assertion fails for an environmental reason.
        launchOptions: {
          args: ["--use-gl=swiftshader", "--enable-unsafe-swiftshader"],
        },
      },
    },
  ],

  webServer: [
    {
      command: "uv run uvicorn app.main:app --host 127.0.0.1 --port " + String(API_PORT),
      cwd: "../api",
      url: `${API_URL}/api/v1/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        // The deterministic offline provider: the copilot's screen is exercised
        // end to end with no key, no network, and no spend.
        LLM_PROVIDER: process.env.LLM_PROVIDER ?? "mock",
        WEB_ORIGIN: WEB_URL,
      },
    },
    {
      // A production build, not `next dev`. The Suspense-boundary failure that
      // broke `/vessels` only surfaced at prerender, and `next dev` would have
      // hidden it here exactly as it did then.
      command: `pnpm build && pnpm start --port ${WEB_PORT}`,
      cwd: ".",
      url: WEB_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 240_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        NEXT_PUBLIC_API_BASE_URL: API_URL,
      },
    },
  ],
});
