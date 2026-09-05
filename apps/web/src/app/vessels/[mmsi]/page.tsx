import type { Metadata } from "next";

import { VesselDetailView } from "./vessel-detail-view";

/**
 * Vessel detail.
 *
 * `params` is a Promise in Next.js 16 — synchronous access was removed.
 */
export async function generateMetadata({
  params,
}: {
  params: Promise<{ mmsi: string }>;
}): Promise<Metadata> {
  const { mmsi } = await params;
  return {
    title: `Vessel ${mmsi}`,
    description: `Observations, track, and metadata for MMSI ${mmsi} in the imported AIS dataset.`,
  };
}

export default async function VesselPage({ params }: { params: Promise<{ mmsi: string }> }) {
  const { mmsi } = await params;
  return <VesselDetailView mmsi={mmsi} />;
}
