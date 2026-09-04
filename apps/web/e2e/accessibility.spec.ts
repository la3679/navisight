import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/**
 * Accessibility, checked automatically and then by hand.
 *
 * SOUL.md §12 requires keyboard operability, visible focus, correct semantics,
 * and identity never carried by colour alone. Two honest caveats up front:
 *
 * **Automated scanning catches a minority of real barriers.** axe finds
 * contrast failures, missing labels, broken landmark structure and bad ARIA. It
 * cannot tell you whether a focus order makes sense, whether a live region
 * announces at a useful moment, or whether a map is usable without a mouse.
 * Passing this file is a floor, not a certificate.
 *
 * **The canvas is not accessible, and no scan will say so.** deck.gl and
 * react-three-fiber render into WebGL, which has no accessibility tree at all.
 * The mitigation is that nothing on those screens is *only* available in the
 * canvas: the vessel list, the filters, the details panel and the analytics
 * tables carry the same information in the DOM. That is a stated design
 * position, not something axe verifies.
 *
 * Serious violations fail the build. Everything axe reports is treated as real
 * until someone explains otherwise in writing — there is no blanket ignore.
 */

const ROUTES = ["/", "/operations", "/vessels", "/analytics", "/ports", "/copilot", "/data"];

/**
 * WCAG 2.1 A and AA. Best-practice rules are excluded from the failing set:
 * they are advisory, they change between axe releases, and a rule that can
 * newly fail on a dependency bump is a flaky gate rather than a standard.
 */
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

for (const route of ROUTES) {
  test(`${route} has no serious or critical accessibility violations`, async ({ page }) => {
    await page.goto(route);
    // Let the first data query settle: an empty page has nothing to fail on,
    // which would make this pass for the wrong reason.
    await page.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page })
      .withTags(TAGS)
      // The WebGL canvas has no accessibility tree to inspect. Excluded so the
      // scan reports on the DOM around it rather than on an opaque element.
      .exclude("canvas")
      .analyze();

    const blocking = results.violations.filter(
      (violation) => violation.impact === "serious" || violation.impact === "critical",
    );

    expect(
      blocking.map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        help: violation.help,
        nodes: violation.nodes.slice(0, 3).map((node) => node.html.slice(0, 120)),
      })),
    ).toEqual([]);
  });
}

test("every page has exactly one h1", async ({ page }) => {
  // A page with no h1, or with several, gives a screen-reader user a broken
  // outline to navigate by. `/operations` had none until this was checked —
  // the map is full-bleed, so its h1 is visually hidden but present.
  for (const route of ROUTES) {
    await page.goto(route);
    await expect(page.locator("h1"), `${route} should have exactly one h1`).toHaveCount(1);
  }
});

test("the skip link is the first thing a keyboard reaches, and it works", async ({ page }) => {
  await page.goto("/");

  await page.keyboard.press("Tab");
  const focused = page.locator(":focus");
  await expect(focused).toHaveText(/skip to main content/i);

  await focused.press("Enter");
  await expect(page).toHaveURL(/#main$/);
});

test("the copilot's question box is reachable and submittable by keyboard alone", async ({
  page,
}) => {
  await page.goto("/copilot");

  const box = page.getByLabel(/ask a question about the archived ais data/i);
  await box.focus();
  await page.keyboard.type("What does this archive contain?");
  await page.keyboard.press("Enter");

  await expect(page.getByText(/you asked:/i)).toBeVisible({ timeout: 45_000 });
});

test("evidence disclosures are operable by keyboard", async ({ page }) => {
  // `<details>`/`<summary>` was chosen over a custom disclosure precisely so
  // this works without any ARIA of our own. Asserted rather than assumed.
  await page.goto("/copilot");
  await page.getByRole("button", { name: /what does this archive contain/i }).click();

  const summary = page.locator("details summary").first();
  await expect(summary).toBeVisible({ timeout: 45_000 });

  await summary.focus();
  await page.keyboard.press("Enter");

  await expect(page.locator("details[open]").first()).toBeVisible();
});

test("claim labels are words, not colours", async ({ page }) => {
  // SOUL.md §12: identity is never carried by colour alone. The support label
  // has to survive being read in greyscale.
  await page.goto("/copilot");
  await page.getByRole("button", { name: /which vessel types are most common/i }).click();
  await expect(page.getByText(/you asked:/i)).toBeVisible({ timeout: 45_000 });

  const labels = page.getByText(/^(Observed|Derived|Heuristic|Interpretation)$/);
  expect(await labels.count()).toBeGreaterThan(0);
});

test("the map legend names each vessel type rather than only colouring it", async ({
  page,
}) => {
  await page.goto("/operations");

  for (const label of ["Cargo", "Tanker", "Passenger"]) {
    await expect(page.getByText(label, { exact: true }).first()).toBeVisible();
  }
});
