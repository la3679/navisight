"use client";

/**
 * The pieces every chart in NaviSight is built from.
 *
 * These are hand-built SVG rather than a charting library, for three reasons
 * that all point the same way:
 *
 * - The mark specification is precise — 2px strokes, ≤24px bars with a rounded
 *   data-end and a square baseline, a 2px surface gap between touching marks,
 *   hairline recessive gridlines. Reaching those through a library's theming
 *   layer is more code than drawing them.
 * - Every chart owes the reader a **table view**. The validated palette carries
 *   a light-mode contrast warning on three hues, and that warning obligates
 *   relief rather than being dismissable, so the table is a requirement here,
 *   not a nicety. Owning the render means the table is built from the same
 *   array as the marks and cannot drift from it.
 * - Keyboard parity with hover has to reach individual marks. That is a
 *   rendering concern, and it is far easier when the elements are ours.
 *
 * Colour is never chosen here. Every mark takes a token from
 * `@/lib/viz/palette`, so light and dark swap in one place.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

/* ------------------------------------------------------------------ layout */

/**
 * Measure a container so charts render at real pixel size.
 *
 * A `viewBox` with a non-uniform aspect would stretch strokes and text, so the
 * SVG is drawn at the width it actually occupies instead.
 */
export function useChartWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = React.useRef<T>(null);
  const [width, setWidth] = React.useState(0);

  React.useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  return [ref, width];
}

export type Padding = { top: number; right: number; bottom: number; left: number };

/** Map a value in `[min, max]` onto `[from, to]`. */
export function scale(
  value: number,
  min: number,
  max: number,
  from: number,
  to: number,
): number {
  if (max === min) return from;
  return from + ((value - min) / (max - min)) * (to - from);
}

/**
 * Round an axis maximum up to a readable number.
 *
 * Axis ticks carry every value that is not directly labelled, so they have to
 * land on numbers a reader can hold — 250,000, not 249,267.
 */
export function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalised = value / magnitude;
  const step = normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10;
  return step * magnitude;
}

/** Evenly spaced ticks from 0 to `max`, inclusive. */
export function ticksTo(max: number, count = 4): number[] {
  return Array.from({ length: count + 1 }, (_, index) => (max / count) * index);
}

/* ------------------------------------------------------------------- chrome */

/** Hairline, solid, one step off the surface. Never dashed; never prominent. */
export function GridLines({
  ticks,
  max,
  x,
  width,
  top,
  bottom,
}: {
  ticks: number[];
  max: number;
  x: number;
  width: number;
  top: number;
  bottom: number;
}) {
  return (
    <g aria-hidden="true">
      {ticks.map((tick) => {
        const y = scale(tick, 0, max, bottom, top);
        return (
          <line
            key={tick}
            x1={x}
            x2={x + width}
            y1={y}
            y2={y}
            stroke="var(--ns-border)"
            strokeWidth={1}
            shapeRendering="crispEdges"
          />
        );
      })}
    </g>
  );
}

/**
 * The floating readout.
 *
 * Positioned in the container's coordinate space rather than following the
 * pointer exactly, and flipped away from the edge it would otherwise overflow.
 * Values lead and labels follow: the reader already knows which series they
 * are on and wants the number.
 */
export function Tooltip({
  x,
  y,
  containerWidth,
  title,
  rows,
}: {
  x: number;
  y: number;
  containerWidth: number;
  title: string;
  rows: { label: string; value: string; color?: string }[];
}) {
  const flip = x > containerWidth * 0.62;
  return (
    <div
      className="pointer-events-none absolute z-10 min-w-[132px] rounded-md border border-[var(--ns-border-strong)] bg-[var(--ns-surface-overlay)] px-2.5 py-1.5 text-xs shadow-lg"
      style={{
        left: flip ? undefined : x + 14,
        right: flip ? containerWidth - x + 14 : undefined,
        top: Math.max(0, y - 12),
      }}
      role="presentation"
    >
      <p className="text-[11px] text-[var(--ns-text-muted)]">{title}</p>
      <ul className="mt-1 space-y-1">
        {rows.map((row) => (
          <li key={row.label} className="flex items-center gap-2">
            {row.color ? (
              // A short stroke, not a filled box: at tooltip density a swatch
              // is data-weight ink doing a label's job.
              <span
                aria-hidden="true"
                className="h-[2px] w-3 shrink-0 rounded-full"
                style={{ backgroundColor: row.color }}
              />
            ) : null}
            <span className="tabular font-[family-name:var(--font-mono)] font-semibold text-[var(--ns-text)]">
              {row.value}
            </span>
            <span className="ml-auto truncate text-[var(--ns-text-muted)]">{row.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* -------------------------------------------------------------- table view */

export type TableColumn<T> = {
  header: string;
  /** Right-aligned and tabular when the column holds numbers. */
  numeric?: boolean;
  cell: (row: T) => React.ReactNode;
};

/**
 * The same data as a table.
 *
 * Not a fallback — a parallel, always-available reading of the chart. It is
 * what makes the figures reachable for a screen reader, in light mode where
 * three palette hues carry a contrast warning, and for anyone who simply wants
 * the numbers.
 */
export function ChartTable<T>({
  rows,
  columns,
  caption,
}: {
  rows: T[];
  columns: TableColumn<T>[];
  caption: string;
}) {
  return (
    <div className="max-h-[300px] overflow-auto rounded-md border border-[var(--ns-border)]">
      <table className="w-full text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead className="sticky top-0 bg-[var(--ns-surface-raised)]">
          <tr>
            {columns.map((column) => (
              <th
                key={column.header}
                scope="col"
                className={cn(
                  "border-b border-[var(--ns-border)] px-2.5 py-1.5 font-medium",
                  "text-[var(--ns-text-secondary)]",
                  column.numeric ? "text-right" : "text-left",
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-b border-[var(--ns-border)] last:border-0">
              {columns.map((column) => (
                <td
                  key={column.header}
                  className={cn(
                    "px-2.5 py-1.5",
                    column.numeric
                      ? "tabular text-right font-[family-name:var(--font-mono)]"
                      : "text-left",
                  )}
                >
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
