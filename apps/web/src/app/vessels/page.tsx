import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingRows } from "@/components/ui/states";
import { VesselSearchView } from "./vessel-search-view";

export const metadata: Metadata = {
  title: "Vessels",
  description: "Search the vessels observed in the imported AIS dataset.",
};

/**
 * Vessel search.
 *
 * The view reads filter state from the URL via `useSearchParams`, which Next
 * cannot resolve at prerender time — so it needs a Suspense boundary, or the
 * static export of this route fails.
 */
export default function VesselsPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-4xl p-4 md:p-6">
          <LoadingRows rows={8} />
        </div>
      }
    >
      <VesselSearchView />
    </Suspense>
  );
}
