/**
 * Small vessel-presentation pieces shared between search results, the map
 * panel, the detail page, and copilot evidence cards.
 *
 * Centralised so a vessel looks and reads the same everywhere, and so the
 * "missing renders as an em dash" rule has one implementation.
 */

"use client";

import { Navigation } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/primitives";
import type { LatestObservation, VesselSummary } from "@/lib/api/types";
import {
  bearingToCardinal,
  EM_DASH,
  formatBearing,
  formatCoordinates,
  formatSpeed,
  formatTimestamp,
} from "@/lib/format";
import { cn } from "@/lib/utils";
import { mapFamilyColor } from "@/lib/viz/palette";

/**
 * A vessel's name, falling back to its MMSI.
 *
 * 17,112 observations in the dataset carry no name at all, so the unnamed case
 * is normal and must still be identifiable.
 */
export function VesselName({ vessel }: { vessel: Pick<VesselSummary, "mmsi" | "name"> }) {
  if (vessel.name) return <>{vessel.name}</>;
  return (
    <span className="text-[var(--ns-text-secondary)]">
      Unnamed vessel{" "}
      <span className="font-[family-name:var(--font-mono)] text-xs">{vessel.mmsi}</span>
    </span>
  );
}

/**
 * A vessel-type chip.
 *
 * Carries a colour dot *and* the label, so type is never conveyed by colour
 * alone (SOUL.md §12).
 */
export function VesselTypeChip({
  label,
  family,
  className,
}: {
  label: string;
  family: string;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs text-[var(--ns-text-secondary)]",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className="size-2 shrink-0 rounded-full"
        style={{ backgroundColor: mapFamilyColor(family) }}
      />
      {label}
    </span>
  );
}

/**
 * A heading arrow.
 *
 * Rotated to the reported bearing, with the numeric bearing and its cardinal
 * point available to screen readers — the rotation alone is not accessible.
 * Renders nothing rotatable when neither heading nor course was reported,
 * which is the case for half the dataset.
 */
export function HeadingArrow({
  headingDegrees,
  courseDegrees,
  className,
}: {
  headingDegrees: number | null;
  courseDegrees: number | null;
  className?: string;
}) {
  const bearing = headingDegrees ?? courseDegrees;
  if (bearing === null) {
    return (
      <span className={cn("text-xs text-[var(--ns-text-muted)]", className)}>{EM_DASH}</span>
    );
  }
  const source = headingDegrees !== null ? "heading" : "course over ground";
  return (
    <span className={cn("inline-flex items-center gap-1", className)}>
      <Navigation
        aria-hidden="true"
        className="size-3.5 text-[var(--ns-text-secondary)]"
        style={{ transform: `rotate(${bearing}deg)` }}
      />
      <span className="sr-only">
        {`${Math.round(bearing)} degrees, ${bearingToCardinal(bearing)}, from ${source}`}
      </span>
      <span aria-hidden="true" className="text-xs tabular text-[var(--ns-text-secondary)]">
        {formatBearing(bearing)}
      </span>
    </span>
  );
}

/** A row in a search-results or nearby list. */
export function VesselResultRow({
  vessel,
  trailing,
  onSelect,
}: {
  vessel: VesselSummary;
  trailing?: React.ReactNode;
  onSelect?: () => void;
}) {
  const content = (
    <>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-[var(--ns-text)]">
          <VesselName vessel={vessel} />
        </p>
        <div className="mt-0.5 flex items-center gap-2">
          <span className="font-[family-name:var(--font-mono)] text-[11px] tabular text-[var(--ns-text-muted)]">
            {vessel.mmsi}
          </span>
          <VesselTypeChip label={vessel.vesselType.label} family={vessel.vesselType.family} />
        </div>
      </div>
      {trailing}
    </>
  );

  const className =
    "flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left transition-colors " +
    "hover:bg-[var(--ns-surface-raised)]";

  if (onSelect) {
    return (
      <button type="button" onClick={onSelect} className={className}>
        {content}
      </button>
    );
  }
  return (
    <Link href={`/vessels/${vessel.mmsi}`} className={className}>
      {content}
    </Link>
  );
}

/**
 * The observation readout used on the map panel and the detail page.
 *
 * Labelled "latest observation" with its timestamp, never "current position"
 * (ADR-0008).
 */
export function LatestObservationSummary({
  observation,
  className,
}: {
  observation: LatestObservation;
  className?: string;
}) {
  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] uppercase tracking-wide text-[var(--ns-text-muted)]">
          Latest observation in dataset
        </span>
        <Badge tone="neutral">{observation.transceiverClass ?? EM_DASH}</Badge>
      </div>
      <p className="font-[family-name:var(--font-mono)] text-xs tabular text-[var(--ns-text-secondary)]">
        {formatTimestamp(observation.timestamp)}
      </p>
      <p className="font-[family-name:var(--font-mono)] text-xs tabular text-[var(--ns-text-secondary)]">
        {formatCoordinates(
          observation.coordinates.longitude,
          observation.coordinates.latitude,
        )}
      </p>
      <dl className="grid grid-cols-3 gap-2 pt-1">
        <div>
          <dt className="text-[10px] uppercase tracking-wide text-[var(--ns-text-muted)]">
            Speed
          </dt>
          <dd className="text-sm tabular">
            {formatSpeed(observation.navigation.speedOverGroundKnots)}
          </dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase tracking-wide text-[var(--ns-text-muted)]">
            Course
          </dt>
          <dd className="text-sm tabular">
            {formatBearing(observation.navigation.courseOverGroundDegrees)}
          </dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase tracking-wide text-[var(--ns-text-muted)]">
            Heading
          </dt>
          <dd className="text-sm tabular">
            {formatBearing(observation.navigation.headingDegrees)}
          </dd>
        </div>
      </dl>
      <p className="text-xs text-[var(--ns-text-secondary)]">
        {observation.navigation.statusLabel}
      </p>
    </div>
  );
}
