import { expect, test } from "@playwright/test";

/**
 * No screen scrolls sideways on a phone.
 *
 * This is one assertion because it catches a whole family of defects with one
 * cheap check, and because two of them were live when it was written:
 *
 * - `/analytics` laid its cards out in a bare `grid`. Tailwind's `grid-cols-N`
 *   expands to `repeat(N, minmax(0, 1fr))`, but a grid with no base column
 *   count gets an implicit `auto` track, whose minimum is the item's
 *   *min-content* — and a grid track never shrinks below that. One long
 *   navigational-status label pushed the document 42 px past the viewport.
 * - `/copilot` rendered its example questions as buttons, and the button
 *   primitive is `whitespace-nowrap`. A whole sentence in a chip made the page
 *   20 px too wide.
 *
 * Neither showed up at desktop widths, and neither is visible in a screenshot
 * of the top of the page. `scrollWidth > clientWidth` finds both instantly.
 *
 * 375 px is the iPhone SE / mini width and the narrowest viewport worth
 * supporting. A tolerance of 1 px absorbs sub-pixel rounding; anything real is
 * far larger than that.
 */

const PHONE = { width: 375, height: 812 };
const TOLERANCE_PX = 1;

const ROUTES = [
  "/",
  "/operations",
  "/vessels",
  "/analytics",
  "/ports",
  "/copilot",
  "/data",
  "/no-such-route",
];

test.use({ viewport: PHONE });

for (const route of ROUTES) {
  test(`${route} fits a 375px viewport without horizontal scroll`, async ({ page }) => {
    await page.goto(route);
    await page.waitForLoadState("networkidle");

    const { clientWidth, scrollWidth, offenders } = await page.evaluate(() => {
      const root = document.documentElement;
      const offenders = Array.from(document.querySelectorAll<HTMLElement>("body *"))
        .filter((element) => {
          const box = element.getBoundingClientRect();
          // An element inside its own horizontally scrollable container is
          // allowed to be wider than the viewport — that is the documented way
          // to carry a wide table or chart.
          let ancestor: HTMLElement | null = element.parentElement;
          while (ancestor && ancestor !== document.body) {
            const overflowX = getComputedStyle(ancestor).overflowX;
            if (overflowX === "auto" || overflowX === "scroll") return false;
            ancestor = ancestor.parentElement;
          }
          return box.width > 0 && box.right > root.clientWidth + 1;
        })
        .slice(0, 5)
        .map((element) => ({
          tag: element.tagName,
          className: String(element.className).slice(0, 80),
          right: Math.round(element.getBoundingClientRect().right),
          text: (element.textContent ?? "").trim().slice(0, 60),
        }));
      return { clientWidth: root.clientWidth, scrollWidth: root.scrollWidth, offenders };
    });

    expect(
      scrollWidth - clientWidth,
      `${route} overflows by ${scrollWidth - clientWidth}px. Widest offenders: ${JSON.stringify(
        offenders,
        null,
        2,
      )}`,
    ).toBeLessThanOrEqual(TOLERANCE_PX);
  });
}
