"use client";

/**
 * A single-series time series.
 *
 * One series per chart on purpose. The two measures NaviSight plots over the
 * day — observations and distinct vessels — differ by an order of magnitude,
 * and a second y-axis is the single most common way to make a chart lie. Two
 * charts sharing an x-range say the same thing honestly.
 *
 * With one series there is no legend: the title already names what is plotted,
 * and a box holding a single swatch would only restate it.
 */

import * as React from "react";

import { formatCount } from "@/lib/format";
import {
  GridLines,
  Tooltip,
  niceMax,
  scale,
  ticksTo,
  useChartWidth,
  type Padding,
} from "./chart-kit";

export type TimePoint = { at: string; value: number };

const PADDING: Padding = { top: 12, right: 16, bottom: 26, left: 52 };

export function TimeSeriesChart({
  points,
  color,
  height = 220,
  valueLabel,
  formatX,
  formatValue = formatCount,
}: {
  points: TimePoint[];
  color: string;
  height?: number;
  /** What one y value means, for the tooltip and the accessible summary. */
  valueLabel: string;
  formatX: (iso: string) => string;
  formatValue?: (value: number) => string;
}) {
  const [containerRef, width] = useChartWidth<HTMLDivElement>();
  const [active, setActive] = React.useState<number | null>(null);

  const plotWidth = Math.max(0, width - PADDING.left - PADDING.right);
  const plotHeight = height - PADDING.top - PADDING.bottom;
  const bottom = PADDING.top + plotHeight;

  const max = niceMax(Math.max(1, ...points.map((point) => point.value)));
  const ticks = ticksTo(max);

  const xAt = React.useCallback(
    (index: number) =>
      PADDING.left +
      (points.length <= 1 ? plotWidth / 2 : (index / (points.length - 1)) * plotWidth),
    [points.length, plotWidth],
  );
  const yAt = React.useCallback(
    (value: number) => scale(value, 0, max, bottom, PADDING.top),
    [max, bottom],
  );

  const path = points.map((point, index) => `${index === 0 ? "M" : "L"}${xAt(index)},${yAt(point.value)}`).join(" ");
  const areaPath =
    points.length > 0
      ? `${path} L${xAt(points.length - 1)},${bottom} L${xAt(0)},${bottom} Z`
      : "";

  /** The crosshair snaps to the nearest sample: nobody aims at a 2px line. */
  const handlePointer = (event: React.PointerEvent<HTMLDivElement>) => {
    if (points.length === 0 || plotWidth <= 0) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const offset = event.clientX - bounds.left - PADDING.left;
    const ratio = Math.min(1, Math.max(0, offset / plotWidth));
    setActive(Math.round(ratio * (points.length - 1)));
  };

  const handleKey = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (points.length === 0) return;
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
      event.preventDefault();
      const step = event.key === "ArrowRight" ? 1 : -1;
      setActive((current) => {
        const next = (current ?? (step > 0 ? -1 : points.length)) + step;
        return Math.min(points.length - 1, Math.max(0, next));
      });
    } else if (event.key === "Escape") {
      setActive(null);
    }
  };

  const activePoint = active !== null ? points[active] : undefined;
  const peak = points.reduce<TimePoint | null>(
    (best, point) => (best === null || point.value > best.value ? point : best),
    null,
  );

  return (
    <div
      ref={containerRef}
      className="relative w-full outline-none focus-visible:ring-2 focus-visible:ring-[var(--ns-accent)]"
      style={{ height }}
      onPointerMove={handlePointer}
      onPointerLeave={() => setActive(null)}
      onKeyDown={handleKey}
      onBlur={() => setActive(null)}
      tabIndex={0}
      role="img"
      aria-label={
        `${valueLabel} over ${points.length} intervals. ` +
        (peak
          ? `Peak ${formatValue(peak.value)} at ${formatX(peak.at)}. `
          : "") +
        "Use the table view for every value, or arrow keys to step through the series."
      }
    >
      {width > 0 ? (
        <svg width={width} height={height} aria-hidden="true">
          <GridLines
            ticks={ticks}
            max={max}
            x={PADDING.left}
            width={plotWidth}
            top={PADDING.top}
            bottom={bottom}
          />

          {ticks.map((tick) => (
            <text
              key={tick}
              x={PADDING.left - 8}
              y={yAt(tick) + 3.5}
              textAnchor="end"
              className="fill-[var(--ns-text-muted)] text-[10px] tabular"
            >
              {formatCount(tick)}
            </text>
          ))}

          {/* An area wash at ~10% keeps the line the loud element. */}
          <path d={areaPath} fill={color} opacity={0.1} />
          <path
            d={path}
            fill="none"
            stroke={color}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />

          {/* X labels are placed sparsely; the crosshair carries the rest. */}
          {points.map((point, index) =>
            index % Math.max(1, Math.ceil(points.length / 6)) === 0 ? (
              <text
                key={point.at}
                x={xAt(index)}
                y={height - 8}
                textAnchor="middle"
                className="fill-[var(--ns-text-muted)] text-[10px] tabular"
              >
                {formatX(point.at)}
              </text>
            ) : null,
          )}

          {activePoint ? (
            <g>
              <line
                x1={xAt(active!)}
                x2={xAt(active!)}
                y1={PADDING.top}
                y2={bottom}
                stroke="var(--ns-border-strong)"
                strokeWidth={1}
              />
              {/* A 2px surface ring keeps the marker legible where it sits on
                  the line it belongs to. */}
              <circle
                cx={xAt(active!)}
                cy={yAt(activePoint.value)}
                r={5}
                fill={color}
                stroke="var(--ns-surface)"
                strokeWidth={2}
              />
            </g>
          ) : null}
        </svg>
      ) : null}

      {activePoint && active !== null ? (
        <Tooltip
          x={xAt(active)}
          y={yAt(activePoint.value)}
          containerWidth={width}
          title={formatX(activePoint.at)}
          rows={[{ label: valueLabel, value: formatValue(activePoint.value), color }]}
        />
      ) : null}
    </div>
  );
}
