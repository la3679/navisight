"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import * as React from "react";
import Map, { Layer, Marker, NavigationControl, Source } from "react-map-gl/maplibre";
import type { MapRef } from "react-map-gl/maplibre";

import type { VesselTrack } from "@/lib/api/types";
import { formatTimestamp } from "@/lib/format";
import { configureMapWorker } from "./map-worker";
import { resolveMapStyle } from "./map-style";

// MapLibre resolves its worker URL when the first map is constructed, so this
// has to run at module scope — before React renders <Map />.
configureMapWorker();

/**
 * A single vessel's path.
 *
 * The line is drawn from real observations only — no interpolation, no
 * smoothing that would invent a position between samples (SOUL.md §4). Start
 * and end are marked so direction is readable without animation.
 *
 * The map is presentational: everything it shows is also available as text on
 * the detail page, so it is never the only route to the information
 * (SOUL.md §12).
 */
export function VesselTrackMap({ track }: { track: VesselTrack }) {
  const mapRef = React.useRef<MapRef | null>(null);
  const style = React.useMemo(() => resolveMapStyle(), []);

  const geojson = React.useMemo(
    () => ({
      type: "Feature" as const,
      properties: {},
      geometry: {
        type: "LineString" as const,
        coordinates: track.points.map((point) => [
          point.coordinates.longitude,
          point.coordinates.latitude,
        ]),
      },
    }),
    [track.points],
  );

  const bounds = React.useMemo(() => {
    if (track.points.length === 0) return null;
    let west = 180;
    let east = -180;
    let south = 90;
    let north = -90;
    for (const point of track.points) {
      west = Math.min(west, point.coordinates.longitude);
      east = Math.max(east, point.coordinates.longitude);
      south = Math.min(south, point.coordinates.latitude);
      north = Math.max(north, point.coordinates.latitude);
    }
    return { west, south, east, north };
  }, [track.points]);

  // Fit once the map is ready. A vessel that never moved produces a degenerate
  // box, so a minimum span keeps the camera from zooming to maximum.
  const handleLoad = React.useCallback(() => {
    if (!bounds || !mapRef.current) return;
    const pad = 0.02;
    mapRef.current.fitBounds(
      [
        [bounds.west - pad, bounds.south - pad],
        [bounds.east + pad, bounds.north + pad],
      ],
      { padding: 40, duration: 0, maxZoom: 12 },
    );
  }, [bounds]);

  const first = track.points[0];
  const last = track.points[track.points.length - 1];

  return (
    <div className="relative h-[360px] w-full overflow-hidden rounded-md border border-[var(--ns-border)]">
      <Map
        ref={mapRef}
        mapStyle={style}
        initialViewState={{ longitude: 0, latitude: 20, zoom: 1 }}
        onLoad={handleLoad}
        attributionControl={false}
        // The canvas is decorative here; the same data is in the table below.
        aria-label={`Track of ${track.points.length} observations`}
        style={{ width: "100%", height: "100%" }}
      >
        <NavigationControl position="top-right" showCompass={false} />

        <Source id="track" type="geojson" data={geojson}>
          {/* A wider, dimmer casing under the line keeps it legible against
              both the dark ground and any basemap the user configures. */}
          <Layer
            id="track-casing"
            type="line"
            paint={{
              "line-color": "#0a111a",
              "line-width": 4.5,
              "line-opacity": 0.6,
            }}
            layout={{ "line-cap": "round", "line-join": "round" }}
          />
          <Layer
            id="track-line"
            type="line"
            paint={{
              "line-color": "#4fd1c5",
              "line-width": 2,
            }}
            layout={{ "line-cap": "round", "line-join": "round" }}
          />
        </Source>

        {first ? (
          <Marker
            longitude={first.coordinates.longitude}
            latitude={first.coordinates.latitude}
            anchor="center"
          >
            <span
              className="block size-2.5 rounded-full border-2 border-[var(--ns-bg)] bg-[var(--ns-text-muted)]"
              title={`First observation ${formatTimestamp(first.timestamp)}`}
            />
          </Marker>
        ) : null}

        {last ? (
          <Marker
            longitude={last.coordinates.longitude}
            latitude={last.coordinates.latitude}
            anchor="center"
          >
            <span
              className="block size-3 rounded-full border-2 border-[var(--ns-bg)] bg-[var(--ns-accent)]"
              title={`Latest observation ${formatTimestamp(last.timestamp)}`}
            />
          </Marker>
        ) : null}
      </Map>

      <div
        className="pointer-events-none absolute bottom-2 left-2 flex items-center gap-3
                   rounded-md bg-[color-mix(in_oklab,var(--ns-surface)_88%,transparent)]
                   px-2 py-1 text-[10px] text-[var(--ns-text-secondary)] backdrop-blur"
      >
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-[var(--ns-text-muted)]" aria-hidden="true" />
          First
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-[var(--ns-accent)]" aria-hidden="true" />
          Latest
        </span>
      </div>
    </div>
  );
}
