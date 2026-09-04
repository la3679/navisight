"use client";

import { OrbitControls } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { RotateCcw } from "lucide-react";
import * as React from "react";

import { Button } from "@/components/ui/primitives";
import { usePrefersReducedMotion, useWebGLSupport } from "@/hooks/client-env";
import {
  EM_DASH,
  bearingToCardinal,
  formatBearing,
  formatDraft,
  formatMeters,
} from "@/lib/format";
import { VesselHull } from "./vessel-hull";

/**
 * The vessel 3D inspector.
 *
 * Three requirements shape this component, all from SOUL.md §12–13:
 *
 * 1. **It is never the only way to get the information.** Every dimension and
 *    the heading are printed as text beneath the canvas, so a screen-reader
 *    user or anyone without WebGL loses nothing.
 * 2. **Reduced motion is honoured.** Auto-rotation is off when the user asks
 *    for reduced motion; manual orbit still works.
 * 3. **It degrades.** No WebGL means a labelled fallback, not a blank box.
 *
 * The model is generated from geometry in code and shaped by this vessel's own
 * reported dimensions. It is representative, and the caption says so.
 */

export function VesselInspector({
  lengthMeters,
  widthMeters,
  draftMeters,
  family,
  headingDegrees,
  vesselName,
}: {
  lengthMeters: number | null;
  widthMeters: number | null;
  draftMeters: number | null;
  family: string;
  headingDegrees: number | null;
  vesselName: string | null;
}) {
  const reducedMotion = usePrefersReducedMotion();
  const supported = useWebGLSupport();
  const [resetKey, setResetKey] = React.useState(0);

  // Fall back to plausible proportions when dimensions were not broadcast,
  // and say so in the caption rather than presenting a guess as measured.
  const hasDimensions = lengthMeters !== null && widthMeters !== null;
  const length = lengthMeters ?? 90;
  const beam = widthMeters ?? Math.max(8, length * 0.16);
  const draft = draftMeters ?? Math.max(2, length * 0.045);

  const description =
    `Representative ${family.toLowerCase()} hull` +
    (vesselName ? ` for ${vesselName}` : "") +
    (hasDimensions
      ? `, ${length} metres long and ${beam} metres in beam`
      : ", drawn at typical proportions because dimensions were not broadcast") +
    (headingDegrees !== null
      ? `, oriented to a heading of ${Math.round(headingDegrees)} degrees (${bearingToCardinal(headingDegrees)}).`
      : ". Heading was not reported, so the model is shown bow-forward.");

  return (
    <div>
      <div className="relative h-[280px] w-full overflow-hidden rounded-md border border-[var(--ns-border)] bg-[var(--ns-bg)]">
        {supported ? (
          <>
            <Canvas
              key={resetKey}
              camera={{ position: [14, 8, 14], fov: 38 }}
              dpr={[1, 1.75]}
              shadows
              // Static scene: render only when something changes, rather than
              // burning a render loop on an idle panel.
              frameloop={reducedMotion ? "demand" : "always"}
              gl={{ antialias: true, powerPreference: "high-performance" }}
              // The canvas duplicates the text below it, so it is hidden from
              // assistive technology rather than announced as an unlabelled image.
              aria-hidden="true"
            >
              <color attach="background" args={["#0a111a"]} />
              <fog attach="fog" args={["#0a111a", 28, 60]} />

              <ambientLight intensity={0.55} />
              <directionalLight
                position={[12, 16, 8]}
                intensity={1.5}
                castShadow
                shadow-mapSize={[1024, 1024]}
              />
              <directionalLight position={[-10, 6, -8]} intensity={0.35} color="#5fb3dd" />

              {/* Waterline plane */}
              <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, 0]} receiveShadow>
                <circleGeometry args={[26, 64]} />
                <meshStandardMaterial
                  color="#0d2033"
                  roughness={0.32}
                  metalness={0.5}
                  transparent
                  opacity={0.92}
                />
              </mesh>

              <group
                rotation={[
                  0,
                  headingDegrees !== null ? -(headingDegrees * Math.PI) / 180 : 0,
                  0,
                ]}
              >
                <VesselHull
                  lengthMeters={length}
                  beamMeters={beam}
                  draftMeters={draft}
                  family={family}
                />
              </group>

              <OrbitControls
                makeDefault
                enablePan={false}
                minDistance={9}
                maxDistance={30}
                // Stop the camera going under the waterline, which looks broken.
                maxPolarAngle={Math.PI / 2.15}
                autoRotate={!reducedMotion}
                autoRotateSpeed={0.5}
              />
            </Canvas>

            <Button
              size="sm"
              variant="secondary"
              className="absolute top-2 right-2"
              onClick={() => setResetKey((key) => key + 1)}
            >
              <RotateCcw aria-hidden="true" />
              Reset view
            </Button>
          </>
        ) : (
          <div className="flex h-full items-center justify-center px-6 text-center">
            <p className="text-xs text-[var(--ns-text-muted)]">
              3D rendering is unavailable in this browser. The vessel&rsquo;s dimensions are
              listed below and in the vessel panel.
            </p>
          </div>
        )}
      </div>

      {/* The accessible equivalent — always rendered, never conditional on 3D. */}
      <p className="sr-only">{description}</p>

      <dl className="mt-3 grid grid-cols-4 gap-2 text-center">
        <div>
          <dt className="text-[10px] tracking-wide text-[var(--ns-text-muted)] uppercase">
            Length
          </dt>
          <dd className="tabular text-xs">{formatMeters(lengthMeters)}</dd>
        </div>
        <div>
          <dt className="text-[10px] tracking-wide text-[var(--ns-text-muted)] uppercase">
            Beam
          </dt>
          <dd className="tabular text-xs">{formatMeters(widthMeters)}</dd>
        </div>
        <div>
          <dt className="text-[10px] tracking-wide text-[var(--ns-text-muted)] uppercase">
            Draft
          </dt>
          <dd className="tabular text-xs">{formatDraft(draftMeters)}</dd>
        </div>
        <div>
          <dt className="text-[10px] tracking-wide text-[var(--ns-text-muted)] uppercase">
            Heading
          </dt>
          <dd className="tabular text-xs">
            {headingDegrees !== null ? formatBearing(headingDegrees) : EM_DASH}
          </dd>
        </div>
      </dl>

      {!hasDimensions ? (
        <p className="mt-2 text-[11px] leading-relaxed text-[var(--ns-text-muted)]">
          This vessel did not broadcast its dimensions, so the model uses typical proportions
          for its type. Only the values shown above come from the data.
        </p>
      ) : null}
    </div>
  );
}
