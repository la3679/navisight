"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { useTheme } from "next-themes";
import * as React from "react";
import * as THREE from "three";

import { useIsMounted, usePrefersReducedMotion } from "@/hooks/client-env";
import { VesselHull } from "./vessel-hull";

/**
 * The landing-page maritime scene.
 *
 * Like every mesh in this project, all of it is generated from geometry in
 * code — sea surface, hulls, channel markers. No third-party model is
 * downloaded or bundled, which keeps the licensing question from arising at
 * all (SOUL.md §15, docs/THIRD_PARTY_ASSETS.md).
 *
 * It is **scenery, not data**. It depicts no particular vessel, port, or
 * moment in the dataset, and the page says so beside it. Dressing a decorative
 * scene up as a visualisation of real traffic would be exactly the kind of
 * false impression SOUL.md §3 forbids.
 *
 * Three constraints shape the implementation:
 *
 * - **Reduced motion stops the animation**, not just slows it. The scene still
 *   renders — a still frame is the point — but nothing moves.
 * - **It never blocks the page.** The route lazy-loads this module, so three.js
 *   is not in the bundle for anyone who does not scroll to it.
 * - **It carries no information**, so it is `aria-hidden`. Everything the page
 *   means is in the text and figures around it.
 */

/**
 * Fixed layout, so the composition is deliberate rather than random per load.
 *
 * `VesselHull` models every ship at a normalised length of 10 units, so each
 * one is scaled here by its real length. That keeps the tug genuinely small
 * beside the tanker instead of making four ships of identical size.
 */
const SCENE_UNITS_PER_METRE = 1 / 26;

/**
 * Two palettes, because the application has two themes.
 *
 * A night harbour on a light page reads as a broken image rather than as a
 * deliberate mood, so the scene follows the theme like every other surface.
 * The two are the same harbour under different light: dusk and overcast day.
 */
type ScenePalette = {
  air: string;
  sea: string;
  seaFar: string;
  sky: [string, string, number];
  sun: { color: string; intensity: number };
  fill: { color: string; intensity: number };
  marker: string;
  fog: [number, number];
};

const PALETTES: Record<"dark" | "light", ScenePalette> = {
  dark: {
    air: "#0a111a",
    sea: "#1b3f5c",
    seaFar: "#16344c",
    sky: ["#5d92bd", "#08131f", 1.15],
    sun: { color: "#ffd9a8", intensity: 2.6 },
    fill: { color: "#7fb4d8", intensity: 0.7 },
    marker: "#4fd1c5",
    fog: [22, 46],
  },
  light: {
    air: "#eef2f6",
    sea: "#8fb2ca",
    seaFar: "#9dbdd2",
    sky: ["#cfe2f2", "#5d7f96", 1.5],
    sun: { color: "#fff4e0", intensity: 2.2 },
    fill: { color: "#b9d4e8", intensity: 0.9 },
    marker: "#0d8b80",
    fog: [26, 58],
  },
};

const FLEET = [
  { family: "Cargo", position: [-3.6, 0, -2.4], heading: 0.42, length: 150, beam: 24 },
  { family: "Tanker", position: [4.4, 0, -5.0], heading: -0.9, length: 180, beam: 32 },
  { family: "Tug", position: [1.2, 0, 2.6], heading: 2.3, length: 30, beam: 10 },
  { family: "Passenger", position: [-4.8, 0, 3.4], heading: 1.15, length: 95, beam: 18 },
] as const;

/**
 * The sea.
 *
 * A subdivided plane displaced by two crossing sine waves. Two is enough to
 * read as water without looking periodic, and it costs a handful of
 * multiplications per vertex per frame rather than a normal-map pipeline.
 */
function displaceSea(geometry: THREE.BufferGeometry, time: number): void {
  const position = geometry.attributes.position as THREE.BufferAttribute;
  for (let index = 0; index < position.count; index += 1) {
    const x = position.getX(index);
    const y = position.getY(index);
    const height = Math.sin(x * 0.32 + time) * 0.16 + Math.sin(y * 0.21 + time * 0.7) * 0.11;
    position.setZ(index, height);
  }
  position.needsUpdate = true;
  geometry.computeVertexNormals();
}

function Sea({ animate, palette }: { animate: boolean; palette: ScenePalette }) {
  // The geometry is reached through a ref rather than a memo because the
  // animation mutates its vertex buffer every frame, which is exactly what a
  // memoised value must not do. R3F owns its lifecycle, including disposal.
  const geometryRef = React.useRef<THREE.PlaneGeometry>(null);

  // Displace once on mount so the still frame — what a reduced-motion user
  // sees — is a sea rather than a flat sheet.
  React.useEffect(() => {
    if (geometryRef.current) displaceSea(geometryRef.current, 0);
  }, []);

  useFrame(({ clock }) => {
    if (!animate || !geometryRef.current) return;
    displaceSea(geometryRef.current, clock.getElapsedTime() * 0.55);
  });

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
      <planeGeometry ref={geometryRef} args={[60, 60, 96, 96]} />
      <meshStandardMaterial
        color={palette.sea}
        roughness={0.42}
        metalness={0.25}
        // Flat shading reads as facets of water at this scale and avoids the
        // plastic look a smooth low-poly surface gets under a single light.
        flatShading
      />
    </mesh>
  );
}

/**
 * The sea beyond the animated patch.
 *
 * The displaced plane is 60 units across, and from this camera its far edge is
 * visible as a diagonal seam against the background. A large flat plane behind
 * it, fully inside the fog, turns that seam into a horizon. It is static and
 * untessellated, so it costs two triangles.
 */
function Horizon({ palette }: { palette: ScenePalette }) {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.06, 0]}>
      <planeGeometry args={[400, 400]} />
      <meshStandardMaterial color={palette.seaFar} roughness={0.5} metalness={0.2} />
    </mesh>
  );
}

/** A lateral channel mark. Small, static, and there to give the eye scale. */
function ChannelMarker({
  position,
  palette,
}: {
  position: [number, number, number];
  palette: ScenePalette;
}) {
  return (
    <group position={position}>
      <mesh position={[0, 0.55, 0]} castShadow>
        <cylinderGeometry args={[0.13, 0.2, 1.1, 8]} />
        <meshStandardMaterial color="#1f3346" roughness={0.8} />
      </mesh>
      <mesh position={[0, 1.25, 0]}>
        <sphereGeometry args={[0.16, 10, 10]} />
        <meshStandardMaterial
          color={palette.marker}
          emissive={palette.marker}
          emissiveIntensity={0.55}
          roughness={0.4}
        />
      </mesh>
    </group>
  );
}

/**
 * A slow orbit around the fleet.
 *
 * The camera moves rather than the vessels, so the hulls keep their heading
 * relative to one another and the scene reads as one harbour seen from a
 * turning viewpoint.
 */
function DriftingCamera({ animate }: { animate: boolean }) {
  useFrame(({ camera, clock }) => {
    if (!animate) return;
    const angle = clock.getElapsedTime() * 0.05;
    camera.position.x = Math.sin(angle) * 12;
    camera.position.z = Math.cos(angle) * 12;
    // A gentle rise and fall reads as swell under the viewpoint rather than as
    // a camera on a crane.
    camera.position.y = 5.6 + Math.sin(angle * 1.6) * 0.24;
    // Aimed slightly below the fleet so the horizon sits high in frame and the
    // sea, not the sky, fills the band the hero text sits over.
    camera.lookAt(0, -0.9, 0);
  });
  return null;
}

export function HarbourScene() {
  const reducedMotion = usePrefersReducedMotion();
  const { resolvedTheme } = useTheme();
  const mounted = useIsMounted();
  const animate = !reducedMotion;

  // `next-themes` cannot resolve the theme during SSR, and this component is
  // client-only anyway, so before mount we would be guessing. Holding the
  // canvas back for one tick is cheaper than mounting a WebGL context with the
  // wrong palette and rebuilding it immediately.
  if (!mounted) return null;

  const palette = PALETTES[resolvedTheme === "light" ? "light" : "dark"];

  return (
    <Canvas
      // Decorative: everything this conveys is in the surrounding copy, so it
      // is hidden from assistive technology rather than announced as an
      // unlabelled image (SOUL.md §12).
      aria-hidden="true"
      camera={{ position: [0, 5.6, 12], fov: 44 }}
      dpr={[1, 1.75]}
      shadows
      // With motion off there is nothing to redraw, so the render loop stops
      // after the first frame instead of spinning on a still image.
      frameloop={animate ? "always" : "demand"}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      style={{ width: "100%", height: "100%" }}
    >
      <color attach="background" args={[palette.air]} />
      {/* Fog fades the far sea into the sky, so the horizon is a gradient
          rather than a hard line where the plane ends. */}
      <fog attach="fog" args={[palette.air, palette.fog[0], palette.fog[1]]} />

      <hemisphereLight args={[palette.sky[0], palette.sky[1], palette.sky[2]]} />
      {/* A low sun off the port bow. The grazing angle is what separates deck
          from hull from sea; an overhead key light flattens all three. */}
      <directionalLight
        position={[-11, 5.5, 7]}
        intensity={palette.sun.intensity}
        color={palette.sun.color}
        castShadow
        shadow-mapSize={[1024, 1024]}
        shadow-camera-left={-16}
        shadow-camera-right={16}
        shadow-camera-top={16}
        shadow-camera-bottom={-16}
      />
      {/* Cool fill from the opposite side, so the shadowed flank is readable
          instead of solid black. */}
      <directionalLight
        position={[9, 4, -6]}
        intensity={palette.fill.intensity}
        color={palette.fill.color}
      />

      <DriftingCamera animate={animate} />
      <Horizon palette={palette} />
      <Sea animate={animate} palette={palette} />

      {FLEET.map((vessel) => (
        <group
          key={vessel.family}
          position={[vessel.position[0], vessel.position[1], vessel.position[2]]}
          rotation={[0, vessel.heading, 0]}
          // VesselHull is modelled at 10 units long whatever the ship, so the
          // real length is reapplied here.
          scale={(vessel.length * SCENE_UNITS_PER_METRE) / 10}
        >
          <VesselHull
            lengthMeters={vessel.length}
            beamMeters={vessel.beam}
            draftMeters={vessel.length * 0.05}
            family={vessel.family}
          />
        </group>
      ))}

      <ChannelMarker position={[-1.3, 0, 4.6]} palette={palette} />
      <ChannelMarker position={[5.6, 0, 0.8]} palette={palette} />
    </Canvas>
  );
}
