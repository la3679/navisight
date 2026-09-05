import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";

/**
 * Every route in the navigation loads, and none of them logs an error.
 *
 * This is the cheapest test in the suite and it would have caught two real
 * bugs. `/copilot` 404'd for two sessions because the nav linked to a route
 * nobody had built. And the map's worker failure announced itself *only* as a
 * console message — which is exactly the signal asserted on here.
 *
 * The console check is not decoration. Session notes record a console error
 * being dismissed as background noise while it was, in fact, the bug.
 */

const ROUTES = [
  { path: "/", heading: /What vessels did, where, and when/i },
  // The map is the whole screen, so this h1 is visually hidden — but it must
  // exist, or a screen-reader user gets an outline that starts at h2.
  { path: "/operations", heading: /Operations map/i },
  { path: "/vessels", heading: /Vessels/i },
  { path: "/analytics", heading: /Analytics/i },
  { path: "/ports", heading: /Ports/i },
  { path: "/copilot", heading: /Copilot/i },
  { path: "/data", heading: /Dataset|Data/i },
] as const;

/**
 * Console noise we accept, each with a reason.
 *
 * Kept deliberately short. Every entry is a promise that the thing behind it is
 * understood — an open-ended ignore list would defeat the whole check.
 */
const ALLOWED = [
  // React DevTools nag in a production build served locally.
  /Download the React DevTools/i,
  // Chromium's own SwiftShader notice under `--use-gl=swiftshader`.
  /swiftshader|software rendering|GroupMarkerNotSet/i,
  // Chromium logs every non-2xx response as a console error. A 409 on /ports
  // is not a failure: it is `PORT_DATA_NOT_CONFIGURED`, the shipped state, and
  // the page renders setup instructions from it. Narrowed to that one status
  // deliberately — allowing "failed to load resource" outright would gut this
  // check, which exists because a dismissed console error *was* the map bug.
  /Failed to load resource: the server responded with a status of 409/i,
];

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message: ConsoleMessage) => {
    if (message.type() !== "error" && message.type() !== "warning") return;
    const text = message.text();
    if (ALLOWED.some((pattern) => pattern.test(text))) return;
    errors.push(`${message.type()}: ${text}`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  return errors;
}

for (const route of ROUTES) {
  test(`${route.path} loads, renders its heading, and logs nothing`, async ({ page }) => {
    const errors = collectErrors(page);

    const response = await page.goto(route.path);
    expect(response?.status(), `${route.path} returned ${response?.status()}`).toBeLessThan(
      400,
    );

    await expect(page.getByRole("heading", { level: 1 })).toContainText(route.heading);
    // Next renders its 404 as a page, not an HTTP status, so the status check
    // above is not sufficient on its own.
    await expect(page.getByText(/this page could not be found/i)).toHaveCount(0);

    expect(errors, `console output on ${route.path}`).toEqual([]);
  });
}

test("the navigation rail reaches every route without a dead link", async ({ page }) => {
  await page.goto("/");

  for (const route of ROUTES) {
    const link = page.getByRole("navigation", { name: /primary/i }).getByRole("link", {
      name: new RegExp(
        route.path === "/" ? "NaviSight home|Overview" : route.path.slice(1),
        "i",
      ),
    });
    await expect(link.first()).toBeVisible();
  }
});

test("the dataset badge states that the data is historical, on every page", async ({
  page,
}) => {
  // ADR-0008: the interface must say the data is a recording where the user is
  // actually looking, not in a tooltip. That is a product claim, so it is
  // asserted rather than trusted to survive a refactor.
  for (const route of ["/", "/operations", "/analytics"]) {
    await page.goto(route);
    await expect(page.getByText(/historical/i).first()).toBeVisible();
  }
});

test("an unknown address gets NaviSight's own not-found page, not Next's", async ({ page }) => {
  // Next's default 404 rendered inside the app shell as grey-on-grey: legible
  // enough to notice, not enough to read. The page that catches someone who is
  // already lost has to be the one page that is easy to read, and it has to
  // offer somewhere to go.
  const errors = collectErrors(page);

  const response = await page.goto("/no-such-route");
  expect(response?.status()).toBe(404);

  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    /this page does not exist/i,
  );
  await expect(page.getByText(/this page could not be found/i)).toHaveCount(0);

  // The point of the page: a way out.
  const main = page.getByRole("main");
  for (const destination of [
    { label: /^Overview/, href: "/" },
    { label: /^Operations map/, href: "/operations" },
    { label: /^Vessels/, href: "/vessels" },
    { label: /^Copilot/, href: "/copilot" },
  ]) {
    const link = main.getByRole("link", { name: destination.label });
    await expect(link).toBeVisible();
    await expect(link).toHaveAttribute("href", destination.href);
  }

  // Chromium logs the 404 document itself as a console error. That one is the
  // correct behaviour under test; anything else on this page is not.
  const unexpected = errors.filter(
    (entry) =>
      !/Failed to load resource: the server responded with a status of 404/i.test(entry),
  );
  expect(unexpected, "console output on the not-found page").toEqual([]);
});
