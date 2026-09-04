"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import type { Layer } from "@deck.gl/core";
import { ScatterplotLayer } from "@deck.gl/layers";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import Map, {
  AttributionControl,
  NavigationControl,
  ScaleControl,
  useControl,
} from "react-map-gl/maplibre";
import type { MapRef, ViewStateChangeEvent } from "react-map-gl/maplibre";

import { api } from "@/lib/api/client";
import type { MapVessel } from "@/lib/api/types";
import { mapFamilyColor, OTHER_COLOR, resolveColor, SEQUENTIAL_RAMP } from "@/lib/viz/palette";
import { configureMapWorker, MAP_LOAD_TIMEOUT_MS } from "./map-worker";
import { DEFAULT_VIEW, FALLBACK_ATTRIBUTION, CUSTOM_STYLE_URL, resolveMapStyle } from "./map-style";

// MapLibre resolves its worker URL when the first map is constructed, so this
// has to run at module scope — before React renders <Map />.
configureMapWorker();

/**
 * The operations map.
 *
 * Rendering strategy, driven by SOUL.md §13 ("the browser never receives the
 * full dataset; thousands of DOM markers is a defect"):
 *
 * - Vessel marks are drawn by **deck.gl on the GPU**, not as DOM elements. At
 *   2,000 visible vessels a marker-per-node approach would stall the main
 *   thread on every pan; a ScatterplotLayer draws them in one pass.
 * - The **server decides** whether to send vessels or aggregated cells based
 *   on viewport area. The client renders whichever it gets. That keeps the
 *   decision next to the data rather than shipping everything and thinning it
 *   in the browser.
 * - Queries are keyed on a **rounded** viewport so a one-pixel pan does not
 *   invalidate the cache, and are debounced so a drag issues one request.
 */

export type MapFilters = {
  vesselType?: number;
  family?: string;
  transceiver?: "A" | "B";
  minSpeed?: number;
  maxSpeed?: number;
};

type Bounds = { west: number; south: number; east: number; north: number };

/** deck.gl layers, mounted as a MapLibre control so both share one canvas. */
function DeckOverlay({ layers }: { layers: Layer[] }) {
  const overlay = useControl<MapboxOverlay>(
    () => new MapboxOverlay({ interleaved: false }),
  );
  // Pushing layers is a side effect on an object React does not own, so it
  // belongs in an effect rather than in the render body.
  React.useEffect(() => {
    overlay.setProps({ layers });
  }, [overlay, layers]);
  return null;
}

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

/** Round to a grid so small pans reuse the cached response. */
function quantize(bounds: Bounds, zoom: number): Bounds {
  const step = zoom > 8 ? 0.01 : zoom > 5 ? 0.1 : 0.5;
  const snap = (value: number) => Math.round(value / step) * step;
  return {
    west: snap(bounds.west),
    south: snap(bounds.south),
    east: snap(bounds.east),
    north: snap(bounds.north),
  };
}

export function OperationsMap({
  filters,
  replayAt,
  selectedMmsi,
  onSelect,
  onStatus,
  focus,
}: {
  filters: MapFilters;
  /** ISO instant for historical replay, or null for latest-known state. */
  replayAt: string | null;
  selectedMmsi: string | null;
  onSelect: (vessel: MapVessel | null) => void;
  onStatus: (status: { total: number; shown: number; mode: string; truncated: boolean }) => void;
  focus: { longitude: number; latitude: number } | null;
}) {
  const mapRef = React.useRef<MapRef | null>(null);
  const [mapInstance, setMapInstance] = React.useState<MapRef | null>(null);
  const style = React.useMemo(() => resolveMapStyle(), []);
  const [viewport, setViewport] = React.useState<{ bounds: Bounds; zoom: number } | null>(null);
  const [hovered, setHovered] = React.useState<MapVessel | null>(null);
  const [groundFailed, setGroundFailed] = React.useState(false);

  const attachMap = React.useCallback((instance: MapRef | null) => {
    mapRef.current = instance;
    setMapInstance(instance);
  }, []);

  const debouncedViewport = useDebounced(viewport, 250);

  const readViewport = React.useCallback(() => {
    const map = mapRef.current?.getMap();
    if (!map) return;
    const bounds = map.getBounds();
    setViewport({
      bounds: {
        west: bounds.getWest(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        north: bounds.getNorth(),
      },
      zoom: map.getZoom(),
    });
  }, []);

  /**
   * Drive the viewport query from the map instance, not from the basemap.
   *
   * Vessel marks are deck.gl geometry projected from the camera; they do not
   * need a single tile of ground. Waiting for `load` — which only fires once
   * every style source has finished — would make a basemap problem look like
   * an empty dataset, which is exactly the failure this page shipped with.
   */
  React.useEffect(() => {
    if (!mapInstance) return;
    const map = mapInstance.getMap();
    readViewport();
    if (map.loaded()) return;

    const onLoad = () => {
      setGroundFailed(false);
      readViewport();
    };
    map.on("load", onLoad);

    // The ground failing is silent by nature — MapLibre simply never finishes.
    // A deadline turns that into something the user can see (SOUL.md §11).
    const timer = setTimeout(() => {
      if (!map.loaded()) setGroundFailed(true);
    }, MAP_LOAD_TIMEOUT_MS);

    return () => {
      clearTimeout(timer);
      map.off("load", onLoad);
    };
  }, [mapInstance, readViewport]);

  // Fly to a vessel handed in from the detail page.
  React.useEffect(() => {
    if (!focus || !mapRef.current) return;
    mapRef.current.flyTo({
      center: [focus.longitude, focus.latitude],
      zoom: 11,
      duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 1200,
    });
  }, [focus]);

  const query = debouncedViewport
    ? quantize(debouncedViewport.bounds, debouncedViewport.zoom)
    : null;

  const { data, isFetching, isError } = useQuery({
    queryKey: ["map", "vessels", query, filters, replayAt],
    queryFn: () =>
      api.mapVessels({
        west: query!.west,
        south: query!.south,
        east: query!.east,
        north: query!.north,
        limit: 3000,
        ...filters,
        ...(replayAt ? { at: replayAt } : {}),
      }),
    enabled: query !== null,
    placeholderData: (previous) => previous,
  });

  React.useEffect(() => {
    if (!data) return;
    onStatus({
      total: data.totalInViewport,
      shown: data.mode === "vessels" ? data.vessels.length : data.clusters.length,
      mode: data.mode,
      truncated: data.truncated,
    });
  }, [data, onStatus]);

  const layers = React.useMemo<Layer[]>(() => {
    if (!data) return [];

    if (data.mode === "clusters") {
      const counts = data.clusters.map((cluster) => cluster.count);
      const maxCount = Math.max(1, ...counts);
      return [
        new ScatterplotLayer({
          id: "clusters",
          data: data.clusters,
          getPosition: (d) => [d.coordinates.longitude, d.coordinates.latitude],
          // Area, not radius, scales with count: a circle whose *area* is
          // proportional is read correctly; scaling the radius exaggerates
          // large values by the square.
          getRadius: (d) => Math.sqrt(d.count / maxCount) * 26,
          radiusUnits: "pixels",
          radiusMinPixels: 4,
          radiusMaxPixels: 34,
          getFillColor: (d) => {
            const ramp = SEQUENTIAL_RAMP;
            const index = Math.min(
              ramp.length - 1,
              Math.floor((d.count / maxCount) * ramp.length),
            );
            const [r, g, b] = resolveColor(ramp[index]!);
            return [r, g, b, 205];
          },
          stroked: true,
          getLineColor: [10, 17, 26, 220],
          lineWidthMinPixels: 1,
          pickable: false,
        }),
      ];
    }

    const vessels = data.vessels;
    return [
      new ScatterplotLayer<MapVessel>({
        id: "vessels",
        data: vessels,
        getPosition: (d) => [d.coordinates.longitude, d.coordinates.latitude],
        getRadius: (d) => (d.mmsi === selectedMmsi ? 9 : 4.5),
        radiusUnits: "pixels",
        radiusMinPixels: 2.5,
        radiusMaxPixels: 12,
        getFillColor: (d) => {
          const [r, g, b] = resolveColor(mapFamilyColor(d.family));
          return [r, g, b, 235];
        },
        // A dark ring gives each mark a 2px separation from its neighbours, so
        // overlapping vessels remain countable.
        stroked: true,
        getLineColor: (d) =>
          d.mmsi === selectedMmsi ? [255, 255, 255, 255] : [10, 17, 26, 190],
        getLineWidth: (d) => (d.mmsi === selectedMmsi ? 2.5 : 1),
        lineWidthUnits: "pixels",
        pickable: true,
        autoHighlight: true,
        highlightColor: [255, 255, 255, 90],
        onHover: ({ object }) => setHovered((object as MapVessel) ?? null),
        onClick: ({ object }) => onSelect((object as MapVessel) ?? null),
        updateTriggers: {
          getRadius: [selectedMmsi],
          getLineColor: [selectedMmsi],
          getLineWidth: [selectedMmsi],
        },
      }),
    ];
  }, [data, selectedMmsi, onSelect]);

  return (
    <div className="relative size-full">
      <Map
        ref={attachMap}
        mapStyle={style}
        initialViewState={DEFAULT_VIEW}
        onMove={(event: ViewStateChangeEvent) => {
          if (event.viewState) readViewport();
        }}
        onMoveEnd={readViewport}
        // A container that grows after mount (a panel opening, a window
        // resize) changes which vessels are in view, so the query follows it.
        onResize={readViewport}
        minZoom={1.5}
        maxZoom={16}
        attributionControl={false}
        cursor={hovered ? "pointer" : "grab"}
        style={{ width: "100%", height: "100%" }}
      >
        <DeckOverlay layers={layers} />
        <NavigationControl position="top-right" visualizePitch={false} />
        <ScaleControl position="bottom-right" unit="nautical" />
        <AttributionControl
          position="bottom-right"
          compact
          customAttribution={CUSTOM_STYLE_URL ? undefined : FALLBACK_ATTRIBUTION}
        />
      </Map>

      {/* Hover readout. Position is fixed rather than following the cursor, so
          it never covers the mark being inspected. */}
      {hovered ? (
        <div
          className="pointer-events-none absolute left-3 top-3 max-w-[240px] rounded-md border
                     border-[var(--ns-border-strong)] bg-[color-mix(in_oklab,var(--ns-surface-overlay)_94%,transparent)]
                     px-2.5 py-2 text-xs shadow-lg backdrop-blur"
          role="status"
        >
          <p className="truncate font-medium text-[var(--ns-text)]">
            {hovered.name ?? `MMSI ${hovered.mmsi}`}
          </p>
          <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-[var(--ns-text-secondary)]">
            <span
              aria-hidden="true"
              className="size-2 rounded-full"
              style={{ backgroundColor: mapFamilyColor(hovered.family) }}
            />
            {hovered.family === "Unknown" ? "Type not reported" : hovered.family}
          </p>
          <p className="mt-0.5 font-[family-name:var(--font-mono)] text-[11px] tabular text-[var(--ns-text-muted)]">
            {hovered.speedOverGroundKnots !== null
              ? `${hovered.speedOverGroundKnots.toFixed(1)} kn`
              : "speed not reported"}
          </p>
        </div>
      ) : null}

      {isFetching ? (
        <div
          className="pointer-events-none absolute right-3 top-3 rounded-full
                     bg-[color-mix(in_oklab,var(--ns-surface-overlay)_92%,transparent)]
                     px-2.5 py-1 text-[11px] text-[var(--ns-text-secondary)] backdrop-blur"
          role="status"
          aria-live="polite"
        >
          Loading vessels…
        </div>
      ) : null}

      {groundFailed ? (
        <div
          className="absolute left-1/2 top-4 z-10 max-w-[min(30rem,90%)] -translate-x-1/2 rounded-md
                     border border-[color-mix(in_oklab,var(--ns-warning)_45%,transparent)]
                     bg-[var(--ns-surface-overlay)] px-3 py-2 text-xs text-[var(--ns-text-secondary)]"
          role="status"
        >
          <span className="font-medium text-[var(--ns-warning)]">
            Basemap could not be drawn.
          </span>{" "}
          Vessel positions below are unaffected — only the coastline is missing.
        </div>
      ) : null}

      {isError ? (
        <div
          className="absolute left-1/2 top-4 -translate-x-1/2 rounded-md border
                     border-[color-mix(in_oklab,var(--ns-critical)_45%,transparent)]
                     bg-[var(--ns-surface-overlay)] px-3 py-2 text-xs text-[var(--ns-critical)]"
          role="alert"
        >
          Could not load vessels for this view.
        </div>
      ) : null}

      {/* Legend. Identity is never colour-alone: each swatch is labelled. */}
      <div
        className="absolute bottom-3 left-3 rounded-md border border-[var(--ns-border)]
                   bg-[color-mix(in_oklab,var(--ns-surface)_90%,transparent)] px-2.5 py-2
                   text-[11px] backdrop-blur"
      >
        <p className="mb-1 font-medium text-[var(--ns-text-secondary)]">Vessel type</p>
        <ul className="space-y-0.5">
          {[
            { label: "Cargo", color: mapFamilyColor("Cargo") },
            { label: "Tanker", color: mapFamilyColor("Tanker") },
            { label: "Passenger", color: mapFamilyColor("Passenger") },
            { label: "Other / not reported", color: OTHER_COLOR },
          ].map((entry) => (
            <li key={entry.label} className="flex items-center gap-1.5 text-[var(--ns-text-muted)]">
              <span
                aria-hidden="true"
                className="size-2 shrink-0 rounded-full"
                style={{ backgroundColor: entry.color }}
              />
              {entry.label}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
