/**
 * Data-visualisation palette.
 *
 * These are the CSS custom properties defined in `globals.css`, referenced by
 * role so a component never hardcodes a hex and light/dark swap in one place.
 *
 * ## Validation
 *
 * The eight categorical hues were checked with the data-viz validator against
 * this application's own surfaces, not a generic one:
 *
 * - dark surface `#101822` — lightness band, chroma floor, adjacent-pair CVD
 *   separation (worst ΔE 8.4), normal-vision floor (19.3), and 3:1 contrast
 *   all PASS.
 * - light surface `#f7f9fb` — same checks PASS, with a contrast WARN on three
 *   hues. That warning obligates *relief*: charts in light mode carry visible
 *   direct labels and a table view. It is not dismissable.
 *
 * ## Why the map uses only three hues
 *
 * A scatter plot puts every pair of colours side by side, and the full eight
 * cannot clear the CVD floors under all-pairs comparison. The first three slots
 * do (worst pair ΔE 9.4 dark / 9.2 light), so the map colours the three largest
 * vessel families and folds everything else into a neutral "Other" — rather
 * than shipping eight hues that a colourblind user cannot separate.
 *
 * Filtering by type remains available for isolating any single family, and the
 * legend plus the selected-vessel panel mean identity is never colour-alone.
 */

/** Categorical series slots, in fixed order. Never cycled. */
export const SERIES_COLORS = [
  "var(--ns-series-1)",
  "var(--ns-series-2)",
  "var(--ns-series-3)",
  "var(--ns-series-4)",
  "var(--ns-series-5)",
  "var(--ns-series-6)",
  "var(--ns-series-7)",
  "var(--ns-series-8)",
] as const;

/** Anything past slot 8, and anything folded out of the map's three. */
export const OTHER_COLOR = "var(--ns-series-other)";

/** Single-hue ramp for magnitude (density, speed). Light → dark. */
export const SEQUENTIAL_RAMP = [
  "var(--ns-seq-1)",
  "var(--ns-seq-2)",
  "var(--ns-seq-3)",
  "var(--ns-seq-4)",
  "var(--ns-seq-5)",
  "var(--ns-seq-6)",
] as const;

/**
 * Reserved status colours. Never reused as a series colour, and always shipped
 * with an icon or label rather than carrying meaning by colour alone.
 */
export const STATUS_COLORS = {
  good: "var(--ns-good)",
  warning: "var(--ns-warning)",
  critical: "var(--ns-critical)",
  info: "var(--ns-info)",
} as const;

/**
 * Colour for a categorical slot.
 *
 * Index is the entity's *stable* position in the domain, not its rank, so a
 * filter that removes a series never repaints the survivors.
 */
export function seriesColor(index: number): string {
  return SERIES_COLORS[index] ?? OTHER_COLOR;
}

/**
 * The vessel families the map colours individually.
 *
 * Three, for the all-pairs CVD reason above. Chosen as the largest families in
 * the profiled dataset among those a reader is most likely to be looking for.
 */
export const MAP_FAMILIES = ["Cargo", "Tanker", "Passenger"] as const;
export type MapFamily = (typeof MAP_FAMILIES)[number];

const MAP_FAMILY_COLORS: Record<string, string> = {
  Cargo: "var(--ns-series-1)",
  Tanker: "var(--ns-series-2)",
  Passenger: "var(--ns-series-3)",
};

/** Map colour for a vessel family, folding unlisted families into "Other". */
export function mapFamilyColor(family: string | null | undefined): string {
  if (!family) return OTHER_COLOR;
  return MAP_FAMILY_COLORS[family] ?? OTHER_COLOR;
}

/** Legend entries for the map, including the explicit "Other" bucket. */
export function mapLegend(): { label: string; color: string }[] {
  return [
    ...MAP_FAMILIES.map((family) => ({
      label: family as string,
      color: mapFamilyColor(family),
    })),
    { label: "Other / not reported", color: OTHER_COLOR },
  ];
}

/**
 * Resolve a CSS custom property to a concrete RGB triple.
 *
 * deck.gl and Three.js need numeric colours; they cannot read `var(...)`. This
 * is the one place the token indirection is collapsed, and it re-reads on
 * theme change so WebGL layers stay in step with the rest of the UI.
 */
export function resolveColor(cssVar: string): [number, number, number] {
  if (typeof window === "undefined") return [120, 140, 160];
  const name = cssVar
    .replace(/^var\(/, "")
    .replace(/\)$/, "")
    .trim();
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return hexToRgb(value) ?? [120, 140, 160];
}

function hexToRgb(hex: string): [number, number, number] | null {
  const match = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  if (!match) return null;
  // The regex has exactly three capturing groups, so a successful match always
  // provides all three.
  return [parseInt(match[1]!, 16), parseInt(match[2]!, 16), parseInt(match[3]!, 16)];
}
