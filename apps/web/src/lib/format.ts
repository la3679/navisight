/**
 * Display formatting.
 *
 * One rule governs this whole module: **missing data renders as an em dash.**
 * Never `null`, never `undefined`, never `NaN`, and never `0` standing in for
 * "not reported" (SOUL.md §11). The dataset is missing heading in 50.6% of
 * observations and IMO in 60.1%, so this is the common path, not an edge case.
 *
 * Units are always labelled. Marine convention is knots for speed, metres for
 * dimensions, degrees for bearings, and nautical miles for distance — with km
 * offered alongside because the audience is not exclusively mariners.
 */

/** The single placeholder for absent data. */
export const EM_DASH = "—";

type Maybe<T> = T | null | undefined;

function isMissing(value: Maybe<number | string>): value is null | undefined {
  return (
    value === null ||
    value === undefined ||
    (typeof value === "number" && !Number.isFinite(value)) ||
    (typeof value === "string" && value.trim() === "")
  );
}

/** Format any optional value, falling back to the em dash. */
export function orDash<T>(value: Maybe<T>, format: (value: T) => string): string {
  return isMissing(value as Maybe<number | string>) ? EM_DASH : format(value as T);
}

export function formatSpeed(knots: Maybe<number>): string {
  return orDash(knots, (value) => `${value.toFixed(1)} kn`);
}

export function formatBearing(degrees: Maybe<number>): string {
  return orDash(degrees, (value) => `${Math.round(value)}°`);
}

export function formatMeters(meters: Maybe<number>): string {
  return orDash(meters, (value) => `${value.toLocaleString()} m`);
}

export function formatDraft(meters: Maybe<number>): string {
  return orDash(meters, (value) => `${value.toFixed(1)} m`);
}

/**
 * Distance in nautical miles with km alongside.
 *
 * Nautical miles lead because this is a maritime product; km is included
 * because most readers think in it.
 */
export function formatDistance(km: Maybe<number>): string {
  return orDash(km, (value) => `${(value / 1.852).toFixed(1)} NM (${value.toFixed(1)} km)`);
}

export function formatCount(value: Maybe<number>): string {
  return orDash(value, (n) => n.toLocaleString());
}

/**
 * Coordinates in the conventional maritime form.
 *
 * Displayed latitude-first with hemisphere letters, which is how a position is
 * spoken and written at sea — even though it is *stored* longitude-first as
 * GeoJSON requires. The two orders serve different audiences and the mismatch
 * is deliberate; this is the only place it is reconciled.
 */
export function formatCoordinates(longitude: Maybe<number>, latitude: Maybe<number>): string {
  if (isMissing(longitude) || isMissing(latitude)) return EM_DASH;
  const lat = `${Math.abs(latitude).toFixed(5)}° ${latitude >= 0 ? "N" : "S"}`;
  const lon = `${Math.abs(longitude).toFixed(5)}° ${longitude >= 0 ? "E" : "W"}`;
  return `${lat}, ${lon}`;
}

/**
 * A timestamp, always with its zone.
 *
 * UTC by default and explicitly labelled. A source event time is never
 * silently rendered in the viewer's local zone (SOUL.md §11, ADR-0009).
 */
export function formatTimestamp(
  iso: Maybe<string>,
  options: { zone?: "utc" | "local"; seconds?: boolean } = {},
): string {
  const { zone = "utc", seconds = true } = options;
  return orDash(iso, (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return EM_DASH;
    const formatter = new Intl.DateTimeFormat("en-GB", {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      ...(seconds ? { second: "2-digit" } : {}),
      hour12: false,
      timeZone: zone === "utc" ? "UTC" : undefined,
    });
    const suffix = zone === "utc" ? " UTC" : " local";
    return `${formatter.format(date)}${suffix}`;
  });
}

/** Time only, for dense readouts such as the replay scrubber. */
export function formatTimeOfDay(iso: Maybe<string>, zone: "utc" | "local" = "utc"): string {
  return orDash(iso, (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return EM_DASH;
    return (
      new Intl.DateTimeFormat("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
        timeZone: zone === "utc" ? "UTC" : undefined,
      }).format(date) + (zone === "utc" ? " UTC" : "")
    );
  });
}

/** Just the date, for the dataset badge. */
export function formatDate(iso: Maybe<string>): string {
  return orDash(iso, (value) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return EM_DASH;
    return new Intl.DateTimeFormat("en-GB", {
      year: "numeric",
      month: "short",
      day: "2-digit",
      timeZone: "UTC",
    }).format(date);
  });
}

/**
 * IMO numbers are conventionally written with the prefix.
 *
 * Stored bare (ADR/normalization strips it); re-applied only for display.
 */
export function formatImo(imo: Maybe<string>): string {
  return orDash(imo, (value) => (value.startsWith("IMO") ? value : `IMO ${value}`));
}

export function formatPercent(value: Maybe<number>, digits = 1): string {
  return orDash(value, (n) => `${n.toFixed(digits)}%`);
}

/** Compact axis labels: 5.9M rather than 5,928,519. */
export function formatCompact(value: Maybe<number>): string {
  return orDash(value, (n) =>
    new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(n),
  );
}

/** Turn a bearing into a cardinal point, for a screen-reader-friendly summary. */
export function bearingToCardinal(degrees: Maybe<number>): string {
  return orDash(degrees, (value) => {
    const points = [
      "N",
      "NNE",
      "NE",
      "ENE",
      "E",
      "ESE",
      "SE",
      "SSE",
      "S",
      "SSW",
      "SW",
      "WSW",
      "W",
      "WNW",
      "NW",
      "NNW",
    ] as const;
    // The modulo guarantees an in-range index; the assertion tells the
    // compiler that, rather than widening the return type to include undefined.
    return points[Math.round((((value % 360) + 360) % 360) / 22.5) % 16]!;
  });
}
