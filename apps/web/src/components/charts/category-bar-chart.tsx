"use client";

/**
 * Horizontal bars for a ranked set of categories.
 *
 * Horizontal because these categories carry long names — "Power-driven vessel
 * pushing ahead or towing alongside" — and a horizontal bar gives a label its
 * own line instead of rotating it 45 degrees.
 *
 * One series, so no legend. Each bar is directly labelled with its value,
 * which is what the light-mode contrast warning on part of the palette
 * obligates: the number never depends on reading the hue.
 */

import * as React from "react";

import { formatCount, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";

export type Category = { key: string; label: string; count: number };

/** ≤24px, so the band's leftover is air rather than a filled slot. */
const BAR_HEIGHT = 18;
const ROW_HEIGHT = BAR_HEIGHT + 14;

export function CategoryBarChart({
  categories,
  total,
  color,
  /** Colour a specific slice differently — used for "Other"-style buckets. */
  mutedKeys,
  mutedColor,
}: {
  categories: Category[];
  total: number;
  color: string;
  mutedKeys?: ReadonlySet<string>;
  mutedColor?: string;
}) {
  const [active, setActive] = React.useState<string | null>(null);
  const max = Math.max(1, ...categories.map((category) => category.count));

  return (
    <ul className="space-y-0" style={{ minHeight: categories.length * ROW_HEIGHT }}>
      {categories.map((category) => {
        const fraction = category.count / max;
        const isMuted = mutedKeys?.has(category.key) ?? false;
        const fill = isMuted ? (mutedColor ?? color) : color;
        const isActive = active === category.key;

        return (
          <li
            key={category.key}
            className={cn(
              "group rounded-sm px-1 py-1 outline-none transition-colors",
              "focus-visible:ring-2 focus-visible:ring-[var(--ns-accent)]",
              isActive ? "bg-[var(--ns-surface-raised)]" : "",
            )}
            // The row is the hit target, not the painted bar: a 4px sliver for a
            // small category is a pinpoint nobody hits.
            tabIndex={0}
            onPointerEnter={() => setActive(category.key)}
            onPointerLeave={() => setActive(null)}
            onFocus={() => setActive(category.key)}
            onBlur={() => setActive(null)}
          >
            <div className="flex items-baseline justify-between gap-3 text-xs">
              <span className="min-w-0 truncate text-[var(--ns-text-secondary)]" title={category.label}>
                {category.label}
              </span>
              <span className="shrink-0 font-[family-name:var(--font-mono)] tabular text-[var(--ns-text)]">
                {formatCount(category.count)}
                <span className="ml-1.5 text-[var(--ns-text-muted)]">
                  {formatPercent((category.count / Math.max(1, total)) * 100)}
                </span>
              </span>
            </div>
            <div
              className="mt-1 w-full rounded-sm bg-[var(--ns-surface-raised)]"
              style={{ height: BAR_HEIGHT * 0.45 }}
              aria-hidden="true"
            >
              <div
                className="h-full rounded-r-[4px] transition-[width]"
                style={{
                  width: `${Math.max(fraction * 100, category.count > 0 ? 1.5 : 0)}%`,
                  backgroundColor: fill,
                  opacity: isActive ? 1 : 0.88,
                }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
