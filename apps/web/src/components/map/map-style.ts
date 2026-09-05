/**
 * Basemap style.
 *
 * By default NaviSight ships a **self-contained** style: ocean, land, and
 * coastlines drawn from a bundled Natural Earth vector file, with no request
 * to any external tile host. That is a deliberate choice rather than a
 * limitation:
 *
 * - it works offline and in CI, so map tests are not gated on a third party;
 * - it sends the user's viewport to nobody — opening the map leaks no
 *   information about what they are looking at;
 * - the muted land/ocean treatment is what lets the vessel marks carry the
 *   eye, which is the point of the operations screen.
 *
 * The trade-off is resolution: Natural Earth 1:110m gives continental
 * outlines, not harbour detail. Set `NEXT_PUBLIC_MAP_STYLE_URL` to any
 * MapLibre style you have the rights to use for a full basemap with ports,
 * bathymetry, and labels.
 *
 * Attribution and licensing for the bundled data: see
 * `docs/THIRD_PARTY_ASSETS.md`. Natural Earth is public domain.
 */

import type { StyleSpecification } from "maplibre-gl";

export const CUSTOM_STYLE_URL = process.env.NEXT_PUBLIC_MAP_STYLE_URL || null;

/** Bundled coastline geometry. ~94 KB, served from the app's own origin. */
export const LAND_GEOJSON_URL = "/geo/ne_110m_land.json";

/** Read a design token so the map follows the application theme. */
function token(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function buildFallbackStyle(): StyleSpecification {
  const ocean = token("--ns-bg", "#0a111a");
  const land = token("--ns-surface-raised", "#16202c");
  const coast = token("--ns-border-strong", "#2e4054");

  return {
    version: 8,
    name: "NaviSight offline ground",
    sources: {
      land: {
        type: "geojson",
        data: LAND_GEOJSON_URL,
      },
    },
    layers: [
      {
        id: "ocean",
        type: "background",
        paint: { "background-color": ocean },
      },
      {
        id: "land-fill",
        type: "fill",
        source: "land",
        paint: { "fill-color": land },
      },
      {
        // A distinct coastline stroke: the land/water boundary is the single
        // most useful reference on a maritime map, so it gets its own line
        // rather than relying on the fill edge.
        id: "coastline",
        type: "line",
        source: "land",
        paint: {
          "line-color": coast,
          "line-width": ["interpolate", ["linear"], ["zoom"], 2, 0.5, 8, 1.4],
        },
      },
    ],
  };
}

/** The style MapLibre should load. A configured URL always wins. */
export function resolveMapStyle(): string | StyleSpecification {
  return CUSTOM_STYLE_URL ?? buildFallbackStyle();
}

/**
 * Initial view.
 *
 * Framed on the continental United States, where the overwhelming majority of
 * this dataset's observations sit. The data also reaches Alaska, Hawaii, and
 * the Pacific territories, so the zoom is deliberately wide.
 */
export const DEFAULT_VIEW = {
  longitude: -95.0,
  latitude: 37.5,
  zoom: 3.4,
} as const;

/** Attribution shown on the map when the bundled ground is in use. */
export const FALLBACK_ATTRIBUTION =
  'Coastlines: <a href="https://www.naturalearthdata.com/" target="_blank" rel="noreferrer">Natural Earth</a> (public domain)';
