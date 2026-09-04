"use client";

import { Edges } from "@react-three/drei";
import * as React from "react";
import * as THREE from "three";

/**
 * A procedurally generated vessel hull.
 *
 * **Every mesh in this project is generated from geometry in code.** No
 * third-party 3D model is downloaded, bundled, or shipped, which removes an
 * entire class of licensing and attribution risk (SOUL.md §15,
 * docs/THIRD_PARTY_ASSETS.md) and keeps the payload to a few kilobytes of
 * vertices instead of a multi-megabyte GLB.
 *
 * It is deliberately *representative*, not a likeness: the hull is shaped by
 * the vessel's own reported length, beam, and draft, and the superstructure
 * follows the broad convention for its type. The UI says so wherever this is
 * displayed — implying it is a model of the actual ship would be a fabrication.
 */

export type HullProfile = {
  /** Where the superstructure sits along the hull, -1 (stern) to 1 (bow). */
  superstructureAt: number;
  /** Superstructure height as a fraction of beam. */
  superstructureHeight: number;
  /** Deck cargo blocks, for container/bulk silhouettes. */
  deckBlocks: number;
  /** Fineness of the bow: higher is sharper. */
  bowSharpness: number;
};

/**
 * Silhouette conventions by vessel family.
 *
 * Real distinctions: a tanker is a flush deck with the house aft, a container
 * ship carries deck stacks, a tug is short with a tall house forward. These
 * are conventions, not measurements.
 */
const PROFILES: Record<string, HullProfile> = {
  Cargo: { superstructureAt: -0.62, superstructureHeight: 1.15, deckBlocks: 4, bowSharpness: 0.72 },
  Tanker: { superstructureAt: -0.68, superstructureHeight: 1.0, deckBlocks: 0, bowSharpness: 0.6 },
  Passenger: { superstructureAt: 0.05, superstructureHeight: 1.6, deckBlocks: 0, bowSharpness: 0.8 },
  Tug: { superstructureAt: 0.18, superstructureHeight: 1.5, deckBlocks: 0, bowSharpness: 0.55 },
  Towing: { superstructureAt: 0.15, superstructureHeight: 1.3, deckBlocks: 0, bowSharpness: 0.5 },
  Fishing: { superstructureAt: 0.1, superstructureHeight: 1.2, deckBlocks: 0, bowSharpness: 0.65 },
  Sailing: { superstructureAt: 0, superstructureHeight: 0.45, deckBlocks: 0, bowSharpness: 0.9 },
  "Pleasure craft": {
    superstructureAt: 0.05, superstructureHeight: 0.8, deckBlocks: 0, bowSharpness: 0.85,
  },
  "High-speed craft": {
    superstructureAt: 0, superstructureHeight: 0.9, deckBlocks: 0, bowSharpness: 0.95,
  },
};

const DEFAULT_PROFILE: HullProfile = {
  superstructureAt: -0.5,
  superstructureHeight: 1.1,
  deckBlocks: 0,
  bowSharpness: 0.7,
};

export function profileFor(family: string): HullProfile {
  return PROFILES[family] ?? DEFAULT_PROFILE;
}

/**
 * Build a hull as an extruded, tapered box.
 *
 * Constructed from a `THREE.Shape` swept along the vertical axis: the deck
 * outline tapers to a point at the bow and a rounded transom at the stern,
 * which reads as a ship from any angle without needing an imported mesh.
 */
function useHullGeometry(length: number, beam: number, depth: number, sharpness: number) {
  return React.useMemo(() => {
    const halfLength = length / 2;
    const halfBeam = beam / 2;
    const bow = halfLength;
    const shoulder = halfLength * sharpness;

    const shape = new THREE.Shape();
    shape.moveTo(bow, 0);
    // Starboard side, bow to stern.
    shape.quadraticCurveTo(shoulder, halfBeam * 0.55, shoulder * 0.72, halfBeam);
    shape.lineTo(-halfLength * 0.82, halfBeam);
    shape.quadraticCurveTo(-halfLength, halfBeam * 0.92, -halfLength, halfBeam * 0.55);
    // Transom.
    shape.lineTo(-halfLength, -halfBeam * 0.55);
    // Port side, stern to bow.
    shape.quadraticCurveTo(-halfLength, -halfBeam * 0.92, -halfLength * 0.82, -halfBeam);
    shape.lineTo(shoulder * 0.72, -halfBeam);
    shape.quadraticCurveTo(shoulder, -halfBeam * 0.55, bow, 0);

    const geometry = new THREE.ExtrudeGeometry(shape, {
      depth,
      bevelEnabled: true,
      bevelThickness: depth * 0.12,
      bevelSize: Math.min(beam, length) * 0.02,
      bevelSegments: 2,
      curveSegments: 12,
    });
    // Extrusion runs along +Z; rotate so the hull sits in the XZ plane with
    // depth on Y, and centre it on the waterline.
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(0, -depth / 2, 0);
    geometry.computeVertexNormals();
    return geometry;
  }, [length, beam, depth, sharpness]);
}

export function VesselHull({
  lengthMeters,
  beamMeters,
  draftMeters,
  family,
  showEdges = true,
}: {
  lengthMeters: number;
  beamMeters: number;
  draftMeters: number;
  family: string;
  showEdges?: boolean;
}) {
  const profile = profileFor(family);

  // Model in a normalized space so the camera framing does not depend on
  // whether the vessel is a 10 m skiff or a 400 m container ship.
  const length = 10;
  const beam = Math.max(1.2, (beamMeters / lengthMeters) * length);
  const hullDepth = Math.max(0.7, (draftMeters / lengthMeters) * length * 2.4);
  const freeboard = hullDepth * 0.55;

  const geometry = useHullGeometry(length, beam, hullDepth, profile.bowSharpness);

  React.useEffect(() => () => geometry.dispose(), [geometry]);

  const houseWidth = beam * 0.68;
  const houseLength = length * 0.13;
  const houseHeight = beam * profile.superstructureHeight * 0.5;

  return (
    <group>
      {/* Hull */}
      <mesh geometry={geometry} castShadow receiveShadow position={[0, freeboard * 0.1, 0]}>
        <meshStandardMaterial color="#2b3d52" roughness={0.72} metalness={0.15} />
        {showEdges ? <Edges threshold={22} color="#4a6280" /> : null}
      </mesh>

      {/* Deck */}
      <mesh position={[0, hullDepth * 0.5 + 0.02, 0]} receiveShadow>
        <boxGeometry args={[length * 0.94, 0.06, beam * 0.94]} />
        <meshStandardMaterial color="#33475e" roughness={0.9} />
      </mesh>

      {/* Superstructure */}
      <group position={[(length / 2) * profile.superstructureAt, hullDepth * 0.5, 0]}>
        <mesh position={[0, houseHeight / 2, 0]} castShadow>
          <boxGeometry args={[houseLength, houseHeight, houseWidth]} />
          <meshStandardMaterial color="#e8eef4" roughness={0.55} />
        </mesh>
        {/* Bridge windows: a darker band, so the model reads as a ship rather
            than a box, without any texture download. */}
        <mesh position={[0, houseHeight * 0.82, 0]}>
          <boxGeometry args={[houseLength * 1.02, houseHeight * 0.16, houseWidth * 1.02]} />
          <meshStandardMaterial color="#14202c" roughness={0.25} metalness={0.4} />
        </mesh>
        <mesh position={[0, houseHeight + 0.35, 0]} castShadow>
          <cylinderGeometry args={[0.045, 0.045, 0.7, 8]} />
          <meshStandardMaterial color="#c9d4de" />
        </mesh>
      </group>

      {/* Deck cargo, for silhouettes that carry it */}
      {Array.from({ length: profile.deckBlocks }, (_, index) => {
        const span = length * 0.52;
        const start = length * 0.06;
        const step = span / Math.max(1, profile.deckBlocks);
        return (
          <mesh
            key={index}
            position={[start + index * step - span * 0.1, hullDepth * 0.5 + beam * 0.22, 0]}
            castShadow
          >
            <boxGeometry args={[step * 0.78, beam * 0.42, beam * 0.72]} />
            <meshStandardMaterial
              color={index % 2 === 0 ? "#3d5670" : "#35495f"}
              roughness={0.85}
            />
          </mesh>
        );
      })}

      {/* Navigation lights: red to port, green to starboard — the real
          convention, and a small detail that makes the scene read correctly to
          anyone who knows it. */}
      <mesh position={[length * 0.34, hullDepth * 0.5 + 0.16, -beam * 0.47]}>
        <sphereGeometry args={[0.075, 10, 10]} />
        <meshBasicMaterial color="#e03a3a" />
      </mesh>
      <mesh position={[length * 0.34, hullDepth * 0.5 + 0.16, beam * 0.47]}>
        <sphereGeometry args={[0.075, 10, 10]} />
        <meshBasicMaterial color="#25c05a" />
      </mesh>
    </group>
  );
}
